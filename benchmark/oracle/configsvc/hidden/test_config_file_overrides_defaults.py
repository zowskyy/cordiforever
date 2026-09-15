import json

from configsvc import load_settings


def test_file_values_win_and_defaults_fill_gaps(tmp_path):
    path = tmp_path / "partial.json"
    path.write_text(json.dumps({"name": "x", "port": 9000, "debug": True}), encoding="utf-8")
    settings = load_settings(path)
    assert settings["port"] == 9000
    assert settings["debug"] is True
    assert settings["timeout"] == 30


def test_repository_config_loads():
    settings = load_settings("config/app.json")
    assert (settings["name"], settings["port"]) == ("svc", 3000)
