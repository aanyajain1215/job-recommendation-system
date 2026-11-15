import numpy as np

from app.services.bandit import (
    D,
    LinUCBPolicy,
    NeuralUCBPolicy,
    build_candidate_features,
    reward_for_event,
    reward_for_reason,
)


def test_build_candidate_features_shape_and_bounds():
    x = build_candidate_features(
        {"skill": 80, "semantic": 70, "experience": 60, "education": 100, "project": 40, "location": 90, "salary": 50, "interest": 70},
        match_score=72,
        missing_required_count=2,
        job_age_days=10,
        applicant_count=5,
        profile_completeness=80,
        is_remote=True,
        salary_disclosed=True,
        family_match=1.0,
        transfer_count=1,
    )
    assert x.shape == (D,)
    assert float(x[0]) == 1.0
    assert np.all(x >= -0.001) and np.all(x <= 1.001)


def test_linucb_select_returns_valid_propensity_and_index():
    # Backward-compatible alias; validates NeuralUCBPolicy behavior
    policy = LinUCBPolicy(alpha=0.7, temperature=0.5)
    assert isinstance(policy, NeuralUCBPolicy)
    X = np.random.default_rng(0).random((5, D))
    dec = policy.select(X, rng=np.random.default_rng(1))
    assert 0 <= dec.index < 5
    assert 0.0 < dec.propensity <= 1.0
    assert abs(sum(dec.propensities) - 1.0) < 1e-3
    assert len(dec.features) == D
    assert dec.policy in ("neural_ucb_softmax", "linucb_softmax")


def test_linucb_update_learns_preference():
    rng = np.random.default_rng(2)
    X = rng.random((3, D))
    policy = NeuralUCBPolicy(alpha=0.1, temperature=0.3)
    # compatibility API for legacy inspection
    theta_before, A_inv_before = policy._theta_and_ainv()
    assert theta_before.shape[0] == D
    assert A_inv_before.shape[0] == A_inv_before.shape[1]

    pred_before = policy._predict_reward(X)
    for _ in range(40):
        policy.update(X[1], 1.0)
        policy.update(X[0], 0.0)
    pred_after = policy._predict_reward(X)

    # online reward learning: rewarded arm's predicted reward should improve
    # relative to the unrewarded arm after updates
    assert (pred_after[1] - pred_before[1]) > (pred_after[0] - pred_before[0])
    assert policy.updates == 80


def test_reward_mappings():
    assert reward_for_event("apply") == 1.0
    assert reward_for_event("dismiss") == 0.0
    assert reward_for_reason("relevant") == 0.85
    assert reward_for_reason("not_relevant") == 0.0
    assert reward_for_event("unknown") is None
