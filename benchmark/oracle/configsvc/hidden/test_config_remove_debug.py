import json


def test_debug_removed_everything_else_intact():
    data = json.load(open("config/app.json", encoding="utf-8"))
    assert data == {"name": "svc", "port": 3000, "database": {"host": "localhost", "port": 5432}, "features": ["login"]}
