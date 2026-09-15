from textkit import slugify


def test_punctuation_removed_hyphens_kept():
    assert slugify("C++ & Python: 2024!") == "c-python-2024" or slugify("C++ & Python: 2024!") == "c--python-2024"
    assert slugify("well-known") == "well-known"
    assert "," not in slugify("a, b, c")
