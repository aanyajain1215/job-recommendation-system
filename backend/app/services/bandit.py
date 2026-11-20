"""Contextual bandit policy (NeuralUCB) for smart exploration.

Upgraded from linear LinUCB to Neural Contextual Bandit (NeuralUCB):
- 2-layer PyTorch MLP predicts expected reward r_hat(x_{u,j})
- UCB exploration bonus: alpha * sqrt(g(x)^T A_inv g(x)) where g(x) is the
  gradient of the predicted reward w.r.t. network parameters
- Sherman-Morrison online inverse covariance updates for A_inv

Maintains compatibility with existing bandit DB state/endpoints and callers:
  - get_policy / reset_cache / latest_artifact_path
  - build_candidate_features / BANDIT_FEATURE_NAMES / D
  - BanditDecision / select / update / apply_online_reward
  - reward_for_event / reward_for_reason
  - LinUCBPolicy alias
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np

log = logging.getLogger(__name__)

ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "ml" / "artifacts"

BANDIT_FEATURE_NAMES = [
    "bias",
    "match_score",
    "skill",
    "semantic",
    "experience",
    "education",
    "project",
    "location",
    "salary",
    "interest",
    "missing_required_count",
    "job_age_days",
    "applicant_count",
    "profile_completeness",
    "is_remote",
    "salary_disclosed",
    "family_match",
    "transfer_count",
]
D = len(BANDIT_FEATURE_NAMES)

# NeuralUCB hyperparams (kept modest for online updates)
HIDDEN_DIM = 32
LAMBDA_REG = 1.0      # ridge / prior precision for A
NU = 1.0               # scaling in some formulations (folded into alpha at API)
LR = 1e-2
WEIGHT_DECAY = 1e-4
ONLINE_STEPS = 1       # SGD steps per observed reward
GRAD_CLIP = 5.0


@dataclass
class BanditDecision:
    index: int
    propensity: float
    scores: list[float]
    propensities: list[float]
    features: list[float]
    policy: str
    model_version: str | None


def _build_mlp(in_dim: int = D, hidden: int = HIDDEN_DIM):
    import torch
    import torch.nn as nn

    model = nn.Sequential(
        nn.Linear(in_dim, hidden),
        nn.ReLU(),
        nn.Linear(hidden, 1),
        nn.Sigmoid(),  # expected reward in (0,1)
    )
    return model


def _flatten_params(model) -> "Any":
    import torch

    return torch.nn.utils.parameters_to_vector([p for p in model.parameters()]).detach()


def _assign_flat_params(model, vec) -> None:
    import torch

    torch.nn.utils.vector_to_parameters(vec, [p for p in model.parameters()])


def _grad_vector(model, x_t: "Any") -> np.ndarray:
    """Gradient of predicted reward f(x) w.r.t. all network parameters."""
    import torch

    model.zero_grad(set_to_none=True)
    x = x_t.view(1, -1)
    pred = model(x).squeeze()
    pred.backward()
    grads = []
    for p in model.parameters():
        if p.grad is None:
            grads.append(torch.zeros_like(p).reshape(-1))
        else:
            grads.append(p.grad.detach().reshape(-1))
    g = torch.cat(grads, dim=0)
    return g.cpu().numpy().astype(np.float64)


class NeuralUCBPolicy:
    """NeuralUCB contextual bandit with Sherman-Morrison inverse covariance updates."""

    def __init__(
        self,
        dim: int = D,
        alpha: float = 0.8,
        temperature: float = 0.5,
        ridge: float = LAMBDA_REG,
        model_version: str | None = None,
        hidden_dim: int = HIDDEN_DIM,
    ) -> None:
        import torch

        self.policy_type = "neural_ucb"
        self.dim = int(dim)
        self.alpha = float(alpha)
        self.temperature = max(1e-3, float(temperature))
        self.ridge = float(ridge)
        self.hidden_dim = int(hidden_dim)
        self.model_version = model_version
        self.updates = 0
        self.trained_at: str | None = None

        torch.manual_seed(42)
        self.model = _build_mlp(self.dim, self.hidden_dim)
        self.model.eval()

        # parameter dimension for gradient covariance
        with torch.no_grad():
            pvec = _flatten_params(self.model)
        self.p_dim = int(pvec.numel())

        # A_inv = (lambda I + sum g g^T)^-1, start at (1/lambda) I
        self.A_inv = (np.eye(self.p_dim, dtype=np.float64) / max(self.ridge, 1e-6))
        # optional: track theta for linear-compat/debug (not used as primary)
        self.theta = np.zeros(self.dim, dtype=np.float64)

        self._opt = None  # lazy optimizer

    def _get_opt(self):
        if self._opt is None:
            import torch

            self._opt = torch.optim.AdamW(self.model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)
        return self._opt

    def _predict_reward(self, X: np.ndarray) -> np.ndarray:
        import torch

        self.model.eval()
        with torch.no_grad():
            xt = torch.tensor(X, dtype=torch.float32)
            preds = self.model(xt).squeeze(-1).detach().cpu().numpy().astype(np.float64)
        if preds.ndim == 0:
            preds = np.array([float(preds)], dtype=np.float64)
        return preds

    def _ucb_bonus(self, x: np.ndarray) -> float:
        import torch

        self.model.eval()
        xt = torch.tensor(x, dtype=torch.float32)
        g = _grad_vector(self.model, xt)
        # bonus = sqrt(g^T A_inv g)
        try:
            val = float(g @ (self.A_inv @ g))
        except Exception:
            val = 0.0
        val = max(0.0, val)
        return math.sqrt(val)

    def predict_scores(self, X: np.ndarray) -> np.ndarray:
        """NeuralUCB score = predicted reward + alpha * gradient-norm UCB bonus."""
        X = np.asarray(X, dtype=np.float64)
        rewards = self._predict_reward(X)
        scores = []
        for i in range(X.shape[0]):
            bonus = self._ucb_bonus(X[i])
            scores.append(float(rewards[i] + self.alpha * bonus))
        return np.asarray(scores, dtype=np.float64)

    # Backward-compat helper (LinUCB API)
    def score(self, x: np.ndarray, *args, **kwargs) -> float:
        s = self.predict_scores(np.asarray(x, dtype=np.float64).reshape(1, -1))
        return float(s[0])

    def _theta_and_ainv(self):
        """Backward-compatible (theta, A_inv) for legacy LinUCB callers/tests.

        Returns a first-layer weight projection vector and the inverse covariance
        matrix used for UCB exploration.
        """
        try:
            # first Linear layer weights: (hidden_dim, dim)
            w = None
            for m in self.model:
                if hasattr(m, "weight") and getattr(m, "weight") is not None:
                    w = m.weight.detach().cpu().numpy()
                    break
            if w is None:
                theta = np.zeros(self.dim, dtype=np.float64)
            else:
                # project to input-dim vector for compatibility
                theta = np.asarray(w.mean(axis=0), dtype=np.float64).reshape(-1)
                if theta.shape[0] != self.dim:
                    theta = np.resize(theta, (self.dim,)).astype(np.float64)
        except Exception:
            theta = np.zeros(self.dim, dtype=np.float64)
        return theta, self.A_inv

    def propensities(self, scores: np.ndarray) -> np.ndarray:
        s = np.asarray(scores, dtype=np.float64) / max(self.temperature, 1e-3)
        s = s - float(np.max(s))
        exp = np.exp(np.clip(s, -60, 60))
        denom = float(np.sum(exp))
        if denom <= 0 or not np.isfinite(denom):
            return np.ones_like(scores, dtype=np.float64) / max(1, len(scores))
        return exp / denom

    def select(self, X: np.ndarray, rng: np.random.Generator | None = None) -> BanditDecision:
        if X.ndim != 2 or X.shape[0] == 0:
            raise ValueError("X must be a non-empty (n,d) array")
        scores = self.predict_scores(X)
        probs = self.propensities(scores)
        rng = rng or np.random.default_rng()
        idx = int(rng.choice(len(probs), p=probs))
        p = float(max(1e-6, probs[idx]))
        return BanditDecision(
            index=idx,
            propensity=round(p, 6),
            scores=[round(float(v), 6) for v in scores.tolist()],
            propensities=[round(float(v), 6) for v in probs.tolist()],
            features=[round(float(v), 6) for v in X[idx].tolist()],
            policy="neural_ucb_softmax",
            model_version=self.model_version,
        )

    def _sherman_morrison_update(self, g: np.ndarray) -> None:
        """A_inv <- A_inv - (A_inv g g^T A_inv) / (1 + g^T A_inv g)."""
        g = np.asarray(g, dtype=np.float64).reshape(-1)
        if g.shape[0] != self.p_dim:
            return
        Ag = self.A_inv @ g
        denom = 1.0 + float(g @ Ag)
        if not np.isfinite(denom) or abs(denom) < 1e-12:
            return
        self.A_inv = self.A_inv - np.outer(Ag, Ag) / denom
        # numerical symmetry guard
        self.A_inv = 0.5 * (self.A_inv + self.A_inv.T)

    def update(self, x: np.ndarray, reward: float) -> None:
        """Online NeuralUCB update: Sherman-Morrison A_inv + SGD step on MLP."""
        import torch
        import torch.nn as nn

        x = np.asarray(x, dtype=np.float64).reshape(-1)
        if x.shape[0] != self.dim:
            return
        r = float(max(0.0, min(1.0, reward)))
        xt = torch.tensor(x, dtype=torch.float32)

        # gradient at current params for exploration covariance (before step)
        try:
            g = _grad_vector(self.model, xt)
            self._sherman_morrison_update(g)
        except Exception as exc:
            log.debug("neural_ucb grad/A_inv update skipped: %s", exc)

        # supervised update toward observed reward
        try:
            opt = self._get_opt()
            loss_fn = nn.MSELoss()
            self.model.train()
            target = torch.tensor([r], dtype=torch.float32)
            for _ in range(max(1, ONLINE_STEPS)):
                opt.zero_grad(set_to_none=True)
                pred = self.model(xt.view(1, -1)).squeeze(-1)
                loss = loss_fn(pred.view(-1), target.view(-1))
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), GRAD_CLIP)
                opt.step()
            self.model.eval()
        except Exception as exc:
            log.debug("neural_ucb param update skipped: %s", exc)

        self.updates += 1

    # --- serialization ---
    def to_payload(self) -> dict[str, Any]:
        import torch

        state = {k: v.detach().cpu() for k, v in self.model.state_dict().items()}
        return {
            "policy_type": "neural_ucb",
            "dim": self.dim,
            "hidden_dim": self.hidden_dim,
            "p_dim": self.p_dim,
            "alpha": self.alpha,
            "temperature": self.temperature,
            "ridge": self.ridge,
            "lambda_reg": self.ridge,
            "model_version": self.model_version,
            "state_dict": state,
            "A_inv": self.A_inv,
            "updates": self.updates,
            "trained_at": self.trained_at,
            "feature_names": list(BANDIT_FEATURE_NAMES),
            # compat fields
            "theta": self.theta,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "NeuralUCBPolicy":
        dim = int(payload.get("dim", D))
        hidden = int(payload.get("hidden_dim", HIDDEN_DIM))
        policy = cls(
            dim=dim,
            alpha=float(payload.get("alpha", 0.8)),
            temperature=float(payload.get("temperature", 0.5)),
            ridge=float(payload.get("ridge", payload.get("lambda_reg", LAMBDA_REG))),
            model_version=payload.get("model_version"),
            hidden_dim=hidden,
        )
        state = payload.get("state_dict") or payload.get("net_state")
        if state is not None:
            try:
                policy.model.load_state_dict(state, strict=False)
                policy.model.eval()
            except Exception as exc:
                log.warning("neural_ucb state load issue: %s", exc)
        A_inv = payload.get("A_inv")
        if A_inv is not None:
            try:
                policy.A_inv = np.asarray(A_inv, dtype=np.float64)
                policy.p_dim = policy.A_inv.shape[0]
            except Exception:
                pass
        # if loading legacy LinUCB payload (A,b) treat as fresh neural with preserved meta
        elif payload.get("A") is not None and payload.get("b") is not None:
            log.info("loading legacy LinUCB artifact as fresh NeuralUCB (meta preserved)")
        policy.updates = int(payload.get("updates", 0))
        policy.trained_at = payload.get("trained_at")
        if "theta" in payload:
            try:
                policy.theta = np.asarray(payload["theta"], dtype=np.float64)
            except Exception:
                pass
        return policy

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.to_payload(), path)

    @classmethod
    def load(cls, path: Path) -> "NeuralUCBPolicy | None":
        try:
            payload = joblib.load(path)
            if not isinstance(payload, dict):
                return None
            return cls.from_payload(payload)
        except Exception as exc:
            log.warning("failed to load bandit artifact %s: %s", path, exc)
            return None


# Backward-compatible alias (existing imports/endpoints)
LinUCBPolicy = NeuralUCBPolicy


_POLICY_CACHE: NeuralUCBPolicy | None = None
_POLICY_CACHE_PATH: str | None = None


ONLINE_ARTIFACT = "bandit_online.joblib"


def latest_artifact_path() -> Path | None:
    """The live policy: learned ONLINE from real interactions only.

    Policies pre-trained on simulated clicks live in ml/artifacts/simulation/
    (a separate study) and are deliberately never loaded here, so a fresh
    install starts uninformed and learns from real users' applies/saves/dismissals.
    """
    if not ARTIFACT_DIR.exists():
        return None
    path = ARTIFACT_DIR / ONLINE_ARTIFACT
    return path if path.exists() else None


def get_policy(alpha: float = 0.8, temperature: float = 0.5) -> NeuralUCBPolicy:
    global _POLICY_CACHE, _POLICY_CACHE_PATH
    path = latest_artifact_path()
    key = str(path) if path else "__fresh__"
    if _POLICY_CACHE is not None and _POLICY_CACHE_PATH == key:
        _POLICY_CACHE.alpha = float(alpha)
        _POLICY_CACHE.temperature = max(1e-3, float(temperature))
        return _POLICY_CACHE
    if path is not None:
        loaded = NeuralUCBPolicy.load(path)
        if loaded is not None:
            loaded.alpha = float(alpha)
            loaded.temperature = max(1e-3, float(temperature))
            loaded.model_version = loaded.model_version or path.stem.replace("bandit_", "")
            _POLICY_CACHE, _POLICY_CACHE_PATH = loaded, key
            return loaded
    fresh = NeuralUCBPolicy(alpha=alpha, temperature=temperature)
    _POLICY_CACHE, _POLICY_CACHE_PATH = fresh, key
    return fresh


def reset_cache() -> None:
    global _POLICY_CACHE, _POLICY_CACHE_PATH
    _POLICY_CACHE = None
    _POLICY_CACHE_PATH = None


def build_candidate_features(
    result_components: dict[str, float],
    match_score: float,
    *,
    missing_required_count: int = 0,
    job_age_days: float = 0.0,
    applicant_count: float = 0.0,
    profile_completeness: float = 0.0,
    is_remote: bool = False,
    salary_disclosed: bool = False,
    family_match: float = 0.0,
    transfer_count: int = 0,
) -> np.ndarray:
    def c(name: str, default: float = 0.0) -> float:
        return float(result_components.get(name, default)) / 100.0

    vec = np.array(
        [
            1.0,
            float(match_score) / 100.0,
            c("skill"),
            c("semantic"),
            c("experience"),
            c("education"),
            c("project"),
            c("location"),
            c("salary"),
            c("interest"),
            min(1.0, float(missing_required_count) / 10.0),
            min(1.0, float(job_age_days) / 60.0),
            min(1.0, float(applicant_count) / 100.0),
            min(1.0, float(profile_completeness) / 100.0),
            1.0 if is_remote else 0.0,
            1.0 if salary_disclosed else 0.0,
            float(family_match),
            min(1.0, float(transfer_count) / 5.0),
        ],
        dtype=np.float64,
    )
    return vec


EVENT_REWARD = {"view": 0.05, "click": 0.30, "save": 0.60, "apply": 1.00, "dismiss": 0.00}
REASON_REWARD = {
    "relevant": 0.85,
    "not_relevant": 0.00,
    "not_interested": 0.05,
    "too_difficult": 0.05,
    "location_issue": 0.10,
    "salary_issue": 0.10,
    "already_applied": 0.50,
    "other": 0.10,
}


def reward_for_event(event_type: Any) -> float | None:
    ev = str(getattr(event_type, "value", event_type)).lower()
    return EVENT_REWARD.get(ev)


def reward_for_reason(reason: Any) -> float | None:
    r = str(getattr(reason, "value", reason)).lower()
    return REASON_REWARD.get(r)


# --- online learning helpers ---

def _latest_bandit_snapshot(db, profile_id, job_id):
    from sqlalchemy import select
    from app.models.recommendation import Recommendation

    recs = db.scalars(
        select(Recommendation)
        .where(Recommendation.profile_id == profile_id, Recommendation.job_id == job_id)
        .order_by(Recommendation.served_at.desc())
        .limit(5)
    ).all()
    for rec in recs:
        snap = rec.snapshot or {}
        b = snap.get("bandit")
        if b and b.get("features"):
            return b
    return None


def apply_online_reward(db, profile_id, job_id, reward: float) -> bool:
    """Update bandit policy from an observed reward for a served bandit action."""
    try:
        from app.core.config import get_settings

        settings = get_settings()
        if not settings.bandit_online_updates:
            return False
        b = _latest_bandit_snapshot(db, profile_id, job_id)
        if not b:
            return False
        features = b.get("features")
        if not features:
            return False
        x = np.asarray(features, dtype=np.float64)
        policy = get_policy(alpha=settings.bandit_alpha, temperature=settings.bandit_temperature)
        policy.update(x, float(reward))
        path = latest_artifact_path()
        if path is None:
            ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
            path = ARTIFACT_DIR / ONLINE_ARTIFACT
        policy.model_version = "online"
        policy.trained_at = datetime.now(timezone.utc).isoformat()
        policy.save(path)
        reset_cache()
        return True
    except Exception as exc:
        log.warning("bandit online update failed: %s", exc)
        return False
