import calculator
from mathlib import add, mean, median, multiply


def test_add():
    assert add(2, 3) == 5


def test_multiply():
    assert multiply(4, 5) == 20


def test_mean():
    assert mean([1, 2, 3]) == 2


def test_median_odd_length():
    assert median([3, 1, 2]) == 2


def test_calculator_add():
    assert calculator.evaluate("add", 1, 2) == 3
