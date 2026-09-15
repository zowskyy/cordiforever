from inventory import Item, find_item


def test_missing_returns_none_existing_found():
    items = [Item("A", "a", 1, 1.0)]
    assert find_item(items, "B") is None
    assert find_item([], "A") is None
    assert find_item(items, "A").sku == "A"
