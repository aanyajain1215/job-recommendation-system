from app.core import rate_limit


def test_sliding_window_blocks_then_recovers():
    rate_limit.reset()
    for i in range(3):
        assert rate_limit.check("k", 3, now=100.0 + i) is None
    wait = rate_limit.check("k", 3, now=103.0)
    assert wait is not None and 0 < wait <= 60
    assert rate_limit.check("k", 3, now=161.0) is None   # oldest hit expired
    assert rate_limit.check("other", 3, now=103.0) is None  # keys are independent


def test_zero_disables():
    assert rate_limit.check("z", 0) is None
