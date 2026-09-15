from textkit import truncate


def test_short_and_exact_unchanged():
    assert truncate("", 3) == ""
    assert truncate("abcd", 4) == "abcd"
    assert truncate("abcdef", 3).startswith("abc")
