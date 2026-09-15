from textkit import slugify, title_case


def test_slugify_simple():
    assert slugify("Hello World") == "hello-world"


def test_title_case_simple():
    assert title_case("hello world") == "Hello World"
