REORDER_THRESHOLD = 10


def total_value(items):
    return sum(item.price for item in items)


def low_stock(items, threshold):
    return [item for item in items if item.qty < threshold]


def find_item(items, sku):
    return next(item for item in items if item.sku == sku)
