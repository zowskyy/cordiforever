import json

from inventory import Item, load_items


def test_category_default_and_loaded(tmp_path):
    path = tmp_path / "items.json"
    path.write_text(json.dumps([
        {"sku": "A", "name": "a", "qty": 1, "price": 1.0, "category": "tools"},
        {"sku": "B", "name": "b", "qty": 1, "price": 1.0},
    ]), encoding="utf-8")
    loaded = load_items(path)
    assert [i.category for i in loaded] == ["tools", "general"]
    assert Item("C", "c", 1, 1.0).category == "general"
