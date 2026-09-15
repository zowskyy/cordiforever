import json

from configsvc import is_debug, load_settings


def test_is_debug_true():
    assert is_debug({"debug": True}) is True


def test_timeout_default(tmp_path):
    path = tmp_path / "minimal.json"
    path.write_text(json.dumps({"name": "x"}), encoding="utf-8")
    assert load_settings(path)["timeout"] == 30
