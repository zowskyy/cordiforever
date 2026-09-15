from configsvc import is_debug


def test_string_and_boolean_values():
    assert is_debug({"debug": "TRUE"}) is True
    assert is_debug({"debug": "False"}) is False
    assert is_debug({"debug": False}) is False
    assert is_debug({}) is False
