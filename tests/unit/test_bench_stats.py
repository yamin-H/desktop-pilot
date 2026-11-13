import pytest

from deskpilot.bench.stats import format_ms, format_rate, per_second, percentile, summarize


def test_nearest_rank_percentiles_of_one_to_a_hundred():
    values = list(range(1, 101))
    assert [percentile(values, p) for p in (1, 50, 95, 99, 100)] == [1, 50, 95, 99, 100]


def test_nearest_rank_on_ten_values():
    values = list(range(1, 11))
    assert (percentile(values, 50), percentile(values, 90), percentile(values, 99)) == (5, 9, 10)


def test_floating_point_noise_does_not_move_a_percentile():
    assert percentile(list(range(1, 101)), 7) == 7  # 0.07 * 100 is 7.000000000000001 in floats


def test_one_value_is_every_percentile():
    assert percentile([4.2], 1) == percentile([4.2], 99) == 4.2


@pytest.mark.parametrize("p", [0, -1, 100.5])
def test_a_percentile_must_be_above_zero_and_at_most_a_hundred(p):
    with pytest.raises(ValueError):
        percentile([1, 2, 3], p)


def test_a_percentile_of_nothing_is_an_error():
    with pytest.raises(ValueError):
        percentile([], 50)
    with pytest.raises(ValueError):
        summarize([])


def test_a_summary_sorts_its_input_and_describes_it():
    summary = summarize([0.3, 0.1, 0.4, 0.2])
    assert summary.count == 4
    assert (summary.minimum, summary.maximum) == (0.1, 0.4)
    assert summary.mean == pytest.approx(0.25)
    assert (summary.p50, summary.p95, summary.p99) == (0.2, 0.4, 0.4)


def test_rates_and_formatting():
    assert per_second(1000, 2.0) == 500
    assert format_ms(0.0123) == "12.3 ms"
    assert format_rate(12345.6) == "12,346/s"
    with pytest.raises(ValueError):
        per_second(10, 0)