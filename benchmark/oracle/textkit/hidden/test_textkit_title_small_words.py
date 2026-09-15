from textkit import title_case


def test_small_words_rules():
    assert title_case("of mice and men") == "Of Mice and Men"
    assert title_case("hello world") == "Hello World"
