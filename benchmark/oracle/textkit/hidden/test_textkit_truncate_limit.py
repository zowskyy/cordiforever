from textkit import truncate


def test_long_text_respects_limit():
    for limit in (4, 5, 10):
        result = truncate("x" * 20, limit)
        assert len(result) == limit and result.endswith("...")
