import inventory
from inventory import Item
from inventory.service import restock


def test_restock_updates_and_returns_item():
    items = [Item("A", "a", 1, 1.0), Item("B", "b", 2, 1.0)]
    returned = restock(items, "A", 4)
    assert returned is items[0] and items[0].qty == 5 and items[1].qty == 2
    assert inventory.restock is restock
