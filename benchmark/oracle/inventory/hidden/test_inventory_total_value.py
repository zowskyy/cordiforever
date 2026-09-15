from inventory import Item, total_value


def test_total_value_uses_quantity():
    items = [Item("A", "a", 3, 2.0), Item("B", "b", 0, 99.0)]
    assert total_value(items) == 6.0
    assert total_value([]) == 0
