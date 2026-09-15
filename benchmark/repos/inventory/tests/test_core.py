from inventory import Item, load_items


def test_load_items_order():
    assert [item.sku for item in load_items("data/items.json")] == ["A-100", "B-200", "C-300"]


def test_item_fields():
    item = Item("X-1", "Thing", 1, 2.0)
    assert (item.sku, item.qty, item.price) == ("X-1", 1, 2.0)
