import json

from .models import Item


def load_items(path):
    with open(path, encoding="utf-8") as handle:
        return [Item(**row) for row in json.load(handle)]


def save_items(path, items):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump([item.__dict__ for item in items], handle)
