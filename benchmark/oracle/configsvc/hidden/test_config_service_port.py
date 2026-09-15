import json


def test_port_changed_and_everything_else_preserved():
    data = json.load(open("config/app.json", encoding="utf-8"))
    assert data == {"name": "svc", "port": 8080, "debug": False, "database": {"host": "localhost", "port": 5432}, "features": ["login"]}


def test_legacy_config_untouched():
    assert json.load(open("legacy/app.json", encoding="utf-8")) == {"name": "svc-old", "port": 9999}
