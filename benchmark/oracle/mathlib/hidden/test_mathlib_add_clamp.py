import mathlib
from mathlib.operations import clamp


def test_clamp_bounds_and_export():
    assert clamp(0, 0, 3) == 0
    assert clamp(3, 0, 3) == 3
    assert clamp(10.5, 1.5, 2.5) == 2.5
    assert mathlib.clamp is clamp
    assert mathlib.add(2, 2) == 4
