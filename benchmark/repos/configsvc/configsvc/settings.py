import json

DEFAULTS = {"port": 80, "debug": False, "timeout": 30}


def load_settings(path):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return {**data, **DEFAULTS}


def is_debug(settings):
    return settings.get("debug") is True
