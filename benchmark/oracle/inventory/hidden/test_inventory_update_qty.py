import json


def test_only_a100_qty_changed_and_backup_untouched():
    data = json.load(open("data/items.json", encoding="utf-8"))
    assert data == [
        {"sku": "A-100", "name": "Bolt", "qty": 25, "price": 0.25},
        {"sku": "B-200", "name": "Nut", "qty": 5, "price": 0.1},
        {"sku": "C-300", "name": "Washer", "qty": 10, "price": 0.05},
    ]
    assert json.load(open("backup/items.json", encoding="utf-8"))[0]["qty"] == 12
