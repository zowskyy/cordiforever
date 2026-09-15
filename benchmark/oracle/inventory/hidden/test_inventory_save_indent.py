import json

from inventory import Item, load_items, save_items


def test_roundtrip_with_indent(tmp_path):
    path = tmp_path / "items.json"
    save_items(path, [Item("A", "a", 1, 2.0)])
    text = path.read_text(encoding="utf-8")
    assert text.startswith('[\n  {\n    "sku"')
    assert load_items(path)[0] == Item("A", "a", 1, 2.0)
    assert json.loads(text)[0]["qty"] == 1
