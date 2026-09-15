from configsvc import describe


def test_describe_format():
    assert describe({"name": "api", "port": 443}) == "api on port 443"
