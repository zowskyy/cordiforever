from mathlib import median


def test_even_lengths():
    assert median([1, 2]) == 1.5
    assert median([10, 0, 5, 5]) == 5


def test_odd_length_unchanged():
    assert median([5, 1, 9]) == 5
