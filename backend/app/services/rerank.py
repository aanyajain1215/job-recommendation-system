"""M2 ranker (DCN-v2) + feature builder + strategy dispatch.

- Heuristic/deterministic baseline remains `scoring.py` component weights (UI/pure).
- `ltr_full` runs PyTorch Deep & Cross Network v2 (DCN-v2) inference.
- `ltr_blend` keeps a learned-primary blend for compatibility, using DCN-v2 as model.

`build_features` extracts continuous, un-clamped domain signals (no hardcoded penalty
multipliers). Standardization is applied via a fitted StandardScaler stored inside the
M2 DCN artifact (train/serve consistent). Legacy LightGBM ranklet loader/helpers are
retained for baseline comparison and backward compatibility.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import get_settings
from app.services.scoring import (
    EXPERIENCE_LEVEL_RANGES,
    ComponentInputs,
    ScoreResult,
    education_rank,
)

log = logging.getLogger(__name__)

ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "ml" / "artifacts"
LGBM_BLEND_WEIGHT = 0.85
LGBM_MAX_DELTA = 15.0  # legacy

# Continuous, un-clamped domain signals for DCN-v2 (standardized by artifact scaler).
FEATURE_ORDER = [
    # semantic (M0 bi-encoder + CE raw outputs)
    "raw_bi_encoder_cosine",
    "cross_encoder_logit",
    "cross_encoder_prob",
    # skill graph / coverage
    "required_coverage_ratio",
    "preferred_coverage_ratio",
    "transfer_sim_mean",
    "transfer_sim_max",
    "missing_required_count",
    "transfer_credit_count",
    # experience (signed deltas)
    "experience_delta_min_years",   # seeker_years - req_min_years
    "experience_delta_max_years",   # seeker_years - req_max_years
    # education
    "education_rank_delta_signed",  # seeker_rank - req_rank
    "education_field_match",        # 1 exact/compatible, 0 mismatch, 0.5 unknown/no bar
    # projects
    "project_skill_overlap_ratio",  # overlap / job_skill_count in [0,1]
    "project_overlap_count",
    # location / remote indicators
    "is_remote_job",
    "location_exact_match",
    "location_preferred_match",
    "location_region_match",
    "seeker_open_to_remote",
    # salary
    "salary_iou",
    "salary_gap_ratio",             # (req_min - seeker_max)/max(req_min,seeker_max) signed-like gap
    "salary_disclosed",
    # career graph
    "career_family_exact_match",
    "career_family_graph_distance",  # 0 same, 1 parent/near, else 2 unknown/far
    # context signals (real, logged)
    "job_age_days",
    "applicant_count",
    "profile_completeness",
    "historical_apply_rate",
    "job_skill_count",
    "seeker_skill_count",
]


@dataclass
class FeatureContext:
    """Per-(profile, job) extras (deterministic/logged)."""

    job_age_days: float = 0.0
    applicant_count: float = 0.0
    profile_completeness: float = 0.0
    historical_apply_rate: float = 0.0
    exploration_flag: float = 0.0
    cross_encoder_logit: float = 0.0
    cross_encoder_prob: float = 0.0


@dataclass
class RankOutcome:
    """Final score + which strategy actually produced it."""

    final: float
    strategy: str
    model_version: str | None = None
    delta_note: str | None = None
    attributions: list[dict[str, Any]] | None = None

    @property
    def used_ltr(self) -> bool:
        return self.strategy in ("ltr_blend", "ltr_full")


# ---------------------------------------------------------------------------
# Feature build (continuous, un-clamped; scaling done by M2 artifact scaler)
# ---------------------------------------------------------------------------

def _safe_ratio(num: float, den: float, default: float = 0.0) -> float:
    if den <= 0:
        return default
    return float(num) / float(den)


def build_features(
    inputs: ComponentInputs,
    result: ScoreResult,
    ctx: FeatureContext | None = None,
) -> list[float]:
    ctx = ctx or FeatureContext()
    possessed = inputs.seeker_skills or {}
    transfers = inputs.transfer_similarities or {}
    job_skills = inputs.job_skills or []
    required = [r for r in job_skills if r.is_required]
    preferred = [r for r in job_skills if not r.is_required]
    job_names = {r.name.lower().strip() for r in job_skills}
    seeker_proj = {s.lower().strip() for s in (inputs.seeker_project_skills or set())}

    def _coverage(reqs: list) -> float:
        if not reqs:
            return 1.0
        hit = 0
        for r in reqs:
            key = r.name.lower().strip()
            if key in possessed or key in transfers:
                hit += 1
        return _safe_ratio(hit, len(reqs), 1.0)

    # transfer similarities (continuous, M1 GraphSAGE evidence for missing skills)
    transfer_vals = [float(v) for v in transfers.values()] if transfers else []
    transfer_sim_mean = float(sum(transfer_vals) / len(transfer_vals)) if transfer_vals else 0.0
    transfer_sim_max = float(max(transfer_vals)) if transfer_vals else 0.0
    transfer_credit_count = float(len(transfer_vals))

    cosine = float(inputs.semantic_cosine) if inputs.semantic_cosine is not None else 0.0

    low, high = EXPERIENCE_LEVEL_RANGES.get(inputs.job_level, (0.0, 10.0))
    years = inputs.years_of_experience
    if years is None:
        exp_delta_min = 0.0
        exp_delta_max = 0.0
    else:
        exp_delta_min = float(years) - float(low)
        exp_delta_max = float(years) - float(high)

    rank_user = education_rank(inputs.seeker_degree)
    rank_req = education_rank(inputs.job_degree)
    if rank_user is not None and rank_req is not None:
        edu_delta = float(rank_user - rank_req)
    else:
        edu_delta = 0.0
    if inputs.job_field and inputs.seeker_field:
        jf = inputs.job_field.strip().lower()
        sf = inputs.seeker_field.strip().lower()
        edu_field_match = 1.0 if (jf == sf or jf in sf or sf in jf) else 0.0
    elif inputs.job_field or inputs.seeker_field:
        edu_field_match = 0.5
    else:
        edu_field_match = 0.5  # unknown/no stated bar

    overlap_count = float(len(seeker_proj & job_names))
    project_overlap_ratio = _safe_ratio(overlap_count, len(job_names), 0.0 if job_names else 1.0)

    # location indicators
    is_remote_job = 1.0 if inputs.job_is_remote else 0.0
    seeker_loc = (inputs.seeker_location or "").strip().lower()
    job_loc = (inputs.job_location or "").strip().lower()
    preferred_locs = {p.lower().strip() for p in (inputs.seeker_preferred_locations or set()) if p}
    location_exact_match = 1.0 if (seeker_loc and job_loc and seeker_loc == job_loc) else 0.0
    location_preferred_match = 1.0 if (job_loc and job_loc in preferred_locs) else 0.0
    seeker_region = seeker_loc.split(",")[-1].strip() if seeker_loc else ""
    job_region = job_loc.split(",")[-1].strip() if job_loc else ""
    location_region_match = 1.0 if (seeker_region and job_region and seeker_region == job_region) else 0.0
    seeker_open_to_remote = 1.0 if inputs.seeker_open_to_remote else 0.0

    # salary IOU and gap ratio
    smin = inputs.seeker_salary_min
    smax = inputs.seeker_salary_max or inputs.seeker_salary_min
    jmin = inputs.job_salary_min
    jmax = inputs.job_salary_max or inputs.job_salary_min
    salary_disclosed = 1.0 if (smin is not None and jmin is not None) else 0.0
    if smin is None or jmin is None:
        salary_iou = 0.0
        salary_gap_ratio = 0.0
    else:
        smin_f, smax_f, jmin_f, jmax_f = float(smin), float(smax), float(jmin), float(jmax)
        inter = max(0.0, min(smax_f, jmax_f) - max(smin_f, jmin_f))
        union = max(smax_f, jmax_f) - min(smin_f, jmin_f)
        salary_iou = (inter / union) if union > 0 else 1.0
        denom = max(abs(jmin_f), abs(smax_f), 1.0)
        salary_gap_ratio = (jmin_f - smax_f) / denom  # >0 means job asks above seeker max

    # career family / graph distance
    seeker_fam = (inputs.seeker_target_family or "").strip().lower()
    job_fam = (inputs.job_family or "").strip().lower()
    career_family_exact_match = 1.0 if (seeker_fam and job_fam and seeker_fam == job_fam) else 0.0
    if inputs.family_graph_distance is None:
        career_family_graph_distance = 2.0 if (seeker_fam and job_fam and seeker_fam != job_fam) else 0.0
    else:
        career_family_graph_distance = float(inputs.family_graph_distance)

    missing_required_count = 0.0
    for r in required:
        key = r.name.lower().strip()
        if key not in possessed and key not in transfers:
            missing_required_count += 1.0

    vector = [
        cosine,
        float(ctx.cross_encoder_logit),
        float(ctx.cross_encoder_prob),
        _coverage(required),
        _coverage(preferred),
        transfer_sim_mean,
        transfer_sim_max,
        missing_required_count,
        transfer_credit_count,
        exp_delta_min,
        exp_delta_max,
        edu_delta,
        edu_field_match,
        project_overlap_ratio,
        overlap_count,
        is_remote_job,
        location_exact_match,
        location_preferred_match,
        location_region_match,
        seeker_open_to_remote,
        float(salary_iou),
        float(salary_gap_ratio),
        float(salary_disclosed),
        career_family_exact_match,
        career_family_graph_distance,
        # Cap context features to stable ranges to avoid OOD extrapolation at inference
        # (training distribution centered on recent jobs/low applicant counts).
        float(max(0.0, min(7.0, ctx.job_age_days))),
        float(max(0.0, min(10.0, ctx.applicant_count))),
        float(max(0.0, min(100.0, ctx.profile_completeness))),
        float(max(0.0, min(1.0, ctx.historical_apply_rate))),
        float(len(job_skills)),
        float(len(possessed)),
    ]
    assert len(vector) == len(FEATURE_ORDER), (len(vector), len(FEATURE_ORDER))
    cleaned = []
    for v in vector:
        try:
            fv = float(v)
        except Exception:
            fv = 0.0
        if not math.isfinite(fv):
            fv = 0.0
        cleaned.append(fv)
    return cleaned


def component_vector(result: ScoreResult) -> list[float]:
    """Legacy/debug vector (component scores + zeros for tail)."""
    comps = result.components or {}
    if isinstance(comps, dict):
        base = [
            float(comps.get("semantic", 0.0)),
            float(comps.get("skill", 0.0)),
            float(comps.get("experience", 0.0)),
            float(comps.get("education", 0.0)),
            float(comps.get("project", 0.0)),
            float(comps.get("location", 0.0)),
            float(comps.get("salary", 0.0)),
            float(comps.get("interest", 0.0)),
        ]
    else:
        base = [
            float(getattr(comps, "semantic", 0.0)),
            float(getattr(comps, "skill", 0.0)),
            float(getattr(comps, "experience", 0.0)),
            float(getattr(comps, "education", 0.0)),
            float(getattr(comps, "project", 0.0)),
            float(getattr(comps, "location", 0.0)),
            float(getattr(comps, "salary", 0.0)),
            float(getattr(comps, "interest", 0.0)),
        ]
    if len(base) >= len(FEATURE_ORDER):
        return base[: len(FEATURE_ORDER)]
    return base + [0.0] * (len(FEATURE_ORDER) - len(base))


# ---------------------------------------------------------------------------
# Legacy LightGBM ranklet loader (kept for comparison / backward compatibility)
# ---------------------------------------------------------------------------

@lru_cache
def _load_lgbm():
    try:
        import lightgbm as lgb  # noqa: PLC0415
    except Exception:  # pragma: no cover
        return None, None, FEATURE_ORDER

    manifests = sorted(ARTIFACT_DIR.glob("ranklet_v*.manifest.json"))
    if not manifests:
        return None, None, FEATURE_ORDER

    manifest_path = manifests[-1]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        model_path = manifest_path.with_suffix("").with_suffix(".txt")
        if not model_path.exists():
            alt = manifest_path.with_name(manifest_path.name.replace(".manifest.json", ".lgb"))
            if alt.exists():
                model_path = alt
        if not model_path.exists():
            return None, None, FEATURE_ORDER
        feature_order = manifest.get("feature_order") or FEATURE_ORDER
        if not isinstance(feature_order, list) or not feature_order:
            return None, None, FEATURE_ORDER
        if feature_order != FEATURE_ORDER[: len(feature_order)]:
            log.warning("lgbm manifest feature order mismatch with live prefix; skipping")
            return None, None, FEATURE_ORDER
        booster = lgb.Booster(model_file=str(model_path))
        version = manifest.get("version") or manifest_path.stem.replace(".manifest", "")
        return booster, str(version), list(feature_order)
    except Exception as exc:  # pragma: no cover
        log.warning("failed to load lgbm ranklet: %s", exc)
        return None, None, FEATURE_ORDER


def _lgbm_score(row: list[float]) -> float | None:
    booster, _version, feature_order = _load_lgbm()
    if booster is None:
        return None
    try:
        width = min(len(feature_order), len(row))
        value = booster.predict([row[:width]])[0]
        return float(value)
    except Exception:  # pragma: no cover
        return None


# ---------------------------------------------------------------------------
# DCN-v2 ranker (PyTorch) - primary M2
# ---------------------------------------------------------------------------

def _build_dcn_model(in_dim: int, cross_layers: int = 2, hidden=(128, 64), dropout: float = 0.2):
    import torch
    import torch.nn as nn

    class CrossNetV2(nn.Module):
        def __init__(self, d: int, layers: int):
            super().__init__()
            self.layers = layers
            self.ws = nn.ModuleList([nn.Linear(d, d, bias=True) for _ in range(layers)])

        def forward(self, x0, return_contrib: bool = False):
            x = x0
            contrib = []
            for layer in self.ws:
                # x_{l+1} = x0 * (W x_l + b) + x_l
                delta = layer(x)
                x = x0 * delta + x
                if return_contrib:
                    contrib.append(delta)
            if return_contrib:
                return x, contrib
            return x

    class DCNv2Ranker(nn.Module):
        def __init__(self, d: int):
            super().__init__()
            self.cross = CrossNetV2(d, cross_layers)
            mlp_layers = []
            prev = d
            for h in hidden:
                mlp_layers += [nn.Linear(prev, h), nn.LayerNorm(h), nn.SiLU(), nn.Dropout(dropout)]
                prev = h
            self.mlp = nn.Sequential(*mlp_layers) if mlp_layers else nn.Identity()
            self.out = nn.Linear(d + prev, 1)  # cross output + deep output

        def forward(self, x, return_attrib: bool = False):
            if return_attrib:
                x_cross, cross_contrib = self.cross(x, return_contrib=True)
            else:
                x_cross = self.cross(x, return_contrib=False)
                cross_contrib = None
            x_deep = self.mlp(x)
            h = torch.cat([x_cross, x_deep], dim=-1)
            logit = self.out(h).squeeze(-1)
            if return_attrib:
                return logit, {"cross": x_cross, "deep": x_deep, "cross_contrib": cross_contrib, "head_weight": self.out.weight.detach()}
            return logit

    return DCNv2Ranker(in_dim)


@lru_cache
def _load_dcn() -> tuple[Any | None, dict | None, str | None]:
    """Load newest DCN-v2 ranker artifact: (model, payload, version)."""
    candidates = sorted(ARTIFACT_DIR.glob("dcn_ranker_v*.pt"))
    if not candidates:
        candidates = sorted(ARTIFACT_DIR.glob("dcn_ranker_v*.pth"))
    if not candidates:
        return None, None, None
    path = candidates[-1]
    try:
        import torch  # noqa: PLC0415

        payload = torch.load(path, map_location="cpu", weights_only=False)
        if not isinstance(payload, dict):
            return None, None, None
        manifest = payload.get("manifest") or {}
        feature_order = manifest.get("feature_order") or payload.get("feature_order") or FEATURE_ORDER
        scaler = payload.get("scaler")
        state = payload.get("state_dict") or payload.get("model_state_dict")
        if state is None:
            # allow raw state dict payload
            state_keys = {"cross.ws.0.weight", "out.weight"}
            if any(k in payload for k in state_keys):
                state = payload
            else:
                return None, None, None
        in_dim = len(feature_order)
        model = _build_dcn_model(
            in_dim,
            cross_layers=int(payload.get("cross_layers", 2)),
            hidden=tuple(payload.get("hidden", [128, 64])),
            dropout=float(payload.get("dropout", 0.2)),
        )
        model.load_state_dict(state, strict=False)
        model.eval()
        meta = {
            "feature_order": list(feature_order),
            "scaler": scaler,  # {"mean": [...], "scale": [...]}
            "version": payload.get("version") or path.stem.replace("dcn_ranker_", ""),
            "manifest": manifest,
        }
        return model, meta, str(meta["version"])
    except Exception as exc:
        log.warning("failed to load DCN ranker %s: %s", path, exc)
        return None, None, None


def _scale_rows(rows: np.ndarray, scaler: dict | None) -> np.ndarray:
    if not scaler:
        return rows.astype(np.float32)
    mean = np.asarray(scaler.get("mean", []), dtype=np.float32)
    scale = np.asarray(scaler.get("scale", []), dtype=np.float32)
    if mean.shape[0] != rows.shape[1] or scale.shape[0] != rows.shape[1]:
        return rows.astype(np.float32)
    scale = np.where(scale == 0, 1.0, scale)
    return ((rows - mean) / scale).astype(np.float32)


def _dcn_predict_batch(rows: list[list[float]], with_attrib: bool = False):
    model, meta, version = _load_dcn()
    if model is None or meta is None:
        return None, version, None
    import torch  # noqa: PLC0415

    feat_order = meta.get("feature_order") or FEATURE_ORDER
    width = len(feat_order)
    arr = np.array([r[:width] + [0.0] * max(0, width - len(r[:width])) for r in rows], dtype=np.float32)
    arr = _scale_rows(arr, meta.get("scaler"))
    x = torch.tensor(arr, dtype=torch.float32)
    with torch.no_grad():
        if with_attrib:
            logits, attrib = model(x, return_attrib=True)
        else:
            logits = model(x, return_attrib=False)
            attrib = None
    scores = logits.detach().cpu().numpy().astype(np.float64)
    return scores, version, attrib


def _dcn_score(row: list[float]) -> tuple[float | None, str | None, list[dict[str, Any]] | None]:
    scores, version, attrib = _dcn_predict_batch([row], with_attrib=True)
    if scores is None:
        return None, version, None
    logit = float(scores[0])
    prob = 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, logit))))
    score_100 = prob * 100.0
    attributions = None
    try:
        if attrib is not None:
            cross = attrib.get("cross")
            deep = attrib.get("deep")
            head_w = attrib.get("head_weight")
            cross_norm = float(cross.abs().mean().item()) if cross is not None else 0.0
            deep_norm = float(deep.abs().mean().item()) if deep is not None else 0.0
            attributions = [{
                "dcn_logit": round(logit, 6),
                "dcn_prob": round(prob, 6),
                "cross_path_mean_abs": round(cross_norm, 6),
                "deep_path_mean_abs": round(deep_norm, 6),
                "head_weight_norm": round(float(head_w.abs().mean().item()), 6) if head_w is not None else None,
            }]
    except Exception:
        attributions = [{"dcn_logit": logit, "dcn_prob": prob}]
    return score_100, version, attributions


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def rerank(result: ScoreResult, features: list[float] | None = None) -> RankOutcome:
    """Apply the configured strategy.

    AI-strict for learned strategies: requires a valid DCN-v2 artifact (no silent fallback).
    """
    requested = get_settings().recommender_strategy
    row = features if features is not None else component_vector(result)

    if requested == "deterministic":
        return RankOutcome(final=float(result.final), strategy="deterministic")

    dcn_value, version, attributions = _dcn_score(row)
    if dcn_value is None or version is None:
        raise RuntimeError(
            f"DCN-v2 ranker artifact required for strategy '{requested}' but none loadable (expected dcn_ranker_v*.pt)"
        )

    try:
        log.info(
            "M2 DCN-v2 inference strategy=%s version=%s score=%.4f attributions=%s",
            requested, version, float(dcn_value), json.dumps(attributions, default=str),
        )
    except Exception:
        pass

    if requested == "ltr_full":
        return RankOutcome(
            final=round(float(dcn_value), 4),
            strategy="ltr_full",
            model_version=str(version),
            attributions=attributions,
        )

    blended = (LGBM_BLEND_WEIGHT * float(dcn_value)) + ((1.0 - LGBM_BLEND_WEIGHT) * float(result.final))
    blended = max(0.0, min(100.0, blended))
    delta = blended - float(result.final)
    return RankOutcome(
        final=round(blended, 4),
        strategy="ltr_blend",
        model_version=str(version),
        delta_note=(f"DCN-v2 set the match score (delta {delta:+.1f} vs heuristic baseline)." if abs(delta) >= 0.05 else None),
        attributions=attributions,
    )


def reset_cache() -> None:
    _load_lgbm.cache_clear()
    _load_dcn.cache_clear()
