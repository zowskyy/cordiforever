import threading

import pytest

from core.context import Context, MODEL_PRESETS, resolve_calibration, calibration_from_context, preset_key_for_model, validate_calibration
from core.errors import CancelledError


REQUIRED_PRESET_KEYS = {"max_tokens", "pruner_budget", "safety", "max_messages", "rounds_per_file", "max_tool_result_bytes"}


def test_model_presets_has_required_keys():
    for key, preset in MODEL_PRESETS.items():
        missing = REQUIRED_PRESET_KEYS - preset.keys()
        assert not missing, f"preset {key!r} missing keys: {missing}"


def test_resolve_calibration_returns_copy_not_table():
    cal = resolve_calibration("qwen2.5-coder:1.5b")
    cal["pruner_budget"] = 9999
    assert MODEL_PRESETS["1.5b"]["pruner_budget"] != 9999


def test_calibration_from_context_uses_explicit_overrides():
    ctx = Context(config={"model": "qwen2.5-coder:1.5b", "calibration": {"pruner_budget": 1234}})
    cal = calibration_from_context(ctx)
    assert cal["pruner_budget"] == 1234


def test_calibration_from_context_falls_back_to_preset():
    ctx = Context(config={"model": "qwen2.5-coder:1.5b"})
    cal = calibration_from_context(ctx)
    assert cal["pruner_budget"] == MODEL_PRESETS["1.5b"]["pruner_budget"]


def test_preset_key_for_model_unknown_falls_back_to_default():
    assert preset_key_for_model("unknown-model") == "1.5b"


def test_validate_calibration_accepts_valid_preset():
    cal = resolve_calibration("qwen2.5-coder:1.5b")
    validate_calibration(cal)


def test_validate_calibration_rejects_missing_keys():
    with pytest.raises(ValueError, match="missing required keys"):
        validate_calibration({"max_tokens": 32768})


def test_validate_calibration_rejects_non_positive_max_tokens():
    cal = resolve_calibration("qwen2.5-coder:1.5b")
    cal["max_tokens"] = 0
    with pytest.raises(ValueError, match="max_tokens must be a positive int"):
        validate_calibration(cal)


def test_validate_calibration_rejects_safety_out_of_range():
    cal = resolve_calibration("qwen2.5-coder:1.5b")
    cal["safety"] = 0.0
    with pytest.raises(ValueError, match="safety must be in"):
        validate_calibration(cal)


def test_validate_calibration_rejects_non_positive_max_tool_result_bytes():
    cal = resolve_calibration("qwen2.5-coder:1.5b")
    cal["max_tool_result_bytes"] = -1
    with pytest.raises(ValueError, match="max_tool_result_bytes must be a positive int"):
        validate_calibration(cal)


def test_resolve_calibration_raises_on_invalid_explicit_override():
    with pytest.raises(ValueError, match="max_tool_result_bytes must be a positive int"):
        resolve_calibration("qwen2.5-coder:1.5b", explicit={"max_tool_result_bytes": -1})

def test_message_roundtrip_with_tool_calls():
    ctx = Context()
    calls = [{"type": "function", "function": {"name": "read_file", "arguments": {"path": "a.txt"}}}]
    msg = ctx.append_message("assistant", "reading", tool_calls=calls)
    assert msg.to_dict()["tool_calls"] == calls


def test_context_append_preserves_tool_calls():
    ctx = Context()
    calls = [{"function": {"name": "read_file", "arguments": {}}}]
    ctx.append_message("assistant", "", tool_calls=calls)
    assert ctx.messages[0].tool_calls == calls


def test_context_clear_removes_all_messages():
    ctx = Context()
    ctx.append_message("user", "one")
    ctx.append_message("assistant", "two")
    ctx.clear_messages()
    assert ctx.messages == []


def test_cancel_event_scoped_to_run():
    ctx = Context()
    ctx.cancel()
    try:
        ctx.check_cancelled()
    except CancelledError:
        pass
    else:
        raise AssertionError("cancel should be set")

    ctx.reset_cancel()
    ctx.check_cancelled()
