import pytest

from deskpilot.ingestion.backoff import BackoffPolicy


def test_delay_doubles_each_time():
    policy = BackoffPolicy(base=1, factor=2, cap=100, jitter=0)
    assert [policy.delay(n) for n in range(5)] == [1, 2, 4, 8, 16]


def test_delay_never_exceeds_cap():
    policy = BackoffPolicy(base=1, factor=2, cap=30, jitter=0)
    assert policy.delay(10) == 30


def test_huge_attempt_number_does_not_overflow():
    policy = BackoffPolicy(base=1, factor=2, cap=30, jitter=0)
    assert policy.delay(100_000) == 30


@pytest.mark.parametrize(("rand_value", "expected"), [(0.0, 5.0), (0.5, 10.0), (1.0, 15.0)])
def test_jitter_spreads_delay_around_the_normal_value(rand_value, expected):
    policy = BackoffPolicy(base=10, factor=2, cap=100, jitter=0.5)
    assert policy.delay(0, rand=lambda: rand_value) == pytest.approx(expected)


def test_delay_is_never_negative():
    policy = BackoffPolicy(base=1, factor=2, cap=30, jitter=1.0)
    assert policy.delay(0, rand=lambda: 0.0) >= 0


@pytest.mark.parametrize(
    "kwargs",
    [{"base": 0}, {"factor": 0.5}, {"base": 10, "cap": 5}, {"jitter": -0.1}, {"jitter": 1.5}],
)
def test_invalid_settings_are_rejected(kwargs):
    with pytest.raises(ValueError):
        BackoffPolicy(**kwargs)
