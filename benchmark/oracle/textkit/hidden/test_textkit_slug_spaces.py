from textkit import slugify


def test_space_runs_collapse():
    assert slugify("  Many    spaced   words ") == "many-spaced-words"
    assert slugify("Hello World") == "hello-world"
