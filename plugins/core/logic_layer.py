from __future__ import annotations

from core.logic_layer import LogicLayer
from core.plugin import Plugin


class LogicLayerPlugin(Plugin):
    name = "logic_layer"
    dependencies = ()

    def __init__(self) -> None:
        super().__init__()
        self._layer = LogicLayer()

    def start(self) -> None:
        pass

    def add_rule(self, rule) -> None:
        self._layer.add_rule(rule)

    def query(self, notes, query_type, context=None):
        return self._layer.query(notes, query_type, context)

    def classify_query(self, query: str) -> str:
        return self._layer.classify_query(query)
