from inventory import Item, low_stock


def test_threshold_inclusive():
    items = [Item("A", "a", 3, 1.0), Item("B", "b", 4, 1.0), Item("C", "c", 5, 1.0)]
    assert [i.sku for i in low_stock(items, 4)] == ["A", "B"]
