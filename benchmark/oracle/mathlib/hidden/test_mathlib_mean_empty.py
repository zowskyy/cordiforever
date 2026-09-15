from mathlib import mean


def test_empty_returns_zero_float():
    result = mean([])
    assert result == 0.0 and isinstance(result, float)


def test_non_empty_unchanged():
    assert mean([1, 2, 3, 4]) == 2.5
