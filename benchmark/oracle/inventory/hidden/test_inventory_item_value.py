from inventory import Item


def test_value_is_derived_property():
    item = Item("A", "a", 3, 1.5)
    assert item.value == 4.5
    item.qty = 0
    assert item.value == 0
