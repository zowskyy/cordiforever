import json


def test_database_port_changed_only():
    data = json.load(open("config/app.json", encoding="utf-8"))
    assert data["database"] == {"host": "localhost", "port": 6543}
    assert data["port"] == 3000
