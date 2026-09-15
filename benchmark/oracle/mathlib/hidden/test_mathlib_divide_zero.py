import pytest

from mathlib import divide


def test_zero_raises_value_error_with_message():
    with pytest.raises(ValueError, match="^division by zero$"):
        divide(5, 0)


def test_normal_division_unchanged():
    assert divide(1, 4) == 0.25
    assert divide(-9, 3) == -3
