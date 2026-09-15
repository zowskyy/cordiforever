import json


def test_search_feature_added_after_login():
    data = json.load(open("config/app.json", encoding="utf-8"))
    assert data["features"] == ["login", "search"]
    assert data["name"] == "svc" and data["database"]["port"] == 5432
