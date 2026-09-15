import pytest

from mathlib import median


def test_empty_raises_value_error():
    with pytest.raises(ValueError, match="^median of empty list$"):
        median([])


def test_non_empty_unchanged():
    assert median([7]) == 7
