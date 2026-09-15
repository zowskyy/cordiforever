import calculator
from mathlib import add, subtract


def test_subtract_values():
    assert subtract(10, 2) == 8
    assert subtract(-1, -1) == 0
    assert subtract(2.5, 0.5) == 2.0


def test_calculator_uses_fixed_subtract_and_add_unchanged():
    assert calculator.evaluate("subtract", 7, 2) == 5
    assert add(1, 1) == 2
