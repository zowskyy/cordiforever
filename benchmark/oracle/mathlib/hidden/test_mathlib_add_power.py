import calculator
import mathlib
from mathlib.operations import power


def test_power_function_and_export():
    assert power(5, 0) == 1
    assert power(2, -1) == 0.5
    assert mathlib.power is power


def test_calculator_power_and_existing_operations():
    assert calculator.evaluate("power", 10, 3) == 1000
    assert calculator.evaluate("multiply", 3, 4) == 12
