import json


def test_database_host_changed_only():
    data = json.load(open("config/app.json", encoding="utf-8"))
    assert data["database"] == {"host": "db.internal", "port": 5432}
    assert data["port"] == 3000 and data["features"] == ["login"]
