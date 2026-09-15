from core.messages import Message


def test_message_to_dict_minimal():
    assert Message("user", "hello").to_dict() == {
        "role": "user",
        "content": "hello",
    }


def test_message_to_dict_with_tool_calls():
    calls = [{"function": {"name": "read_file", "arguments": {"path": "x"}}}]
    data = Message("assistant", "", tool_calls=calls).to_dict()
    assert data["tool_calls"] == calls


def test_message_to_dict_with_tool_name():
    data = Message("tool", "result", tool_name="read_file").to_dict()
    assert data["tool_name"] == "read_file"


def test_message_from_dict_roundtrip():
    original = Message(
        "assistant",
        "x",
        tool_name=None,
        tool_calls=[{"function": {"name": "x", "arguments": {}}}],
    )
    restored = Message.from_dict(original.to_dict())
    assert restored == original
