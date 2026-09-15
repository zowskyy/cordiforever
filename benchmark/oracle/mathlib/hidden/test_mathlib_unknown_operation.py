import pytest

import calculator


def test_unknown_operation_message_contains_name():
    with pytest.raises(ValueError, match="^unknown operation: sqrt$"):
        calculator.evaluate("sqrt", 4, 0)


def test_known_operations_still_work():
    assert calculator.evaluate("divide", 8, 2) == 4
