from textkit import slugify


def test_no_edge_hyphens():
    assert slugify("--a b--") == "a-b"
    assert slugify("Hello World") == "hello-world"
