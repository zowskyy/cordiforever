import textkit
from textkit.formatting import word_count


def test_word_count_and_export():
    assert word_count("  lead and trail  ") == 3
    assert word_count("one\ttwo\nthree") == 3
    assert textkit.word_count is word_count
