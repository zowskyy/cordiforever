from __future__ import annotations

from core.reality import RealityProjector
from core.plugin import Plugin


class RealityProjectorPlugin(Plugin):
    name = "reality_projector"
    dependencies = ("event_logger",)

    def __init__(self, snapshot_threshold: int = 50) -> None:
        super().__init__()
        self.snapshot_threshold = snapshot_threshold
        self._projector = None

    def register(self, context) -> None:
        super().register(context)
        event_log = context.plugins.get("event_log")
        if event_log is not None:
            self._projector = RealityProjector(event_log, snapshot_threshold=self.snapshot_threshold)

    def start(self) -> None:
        pass

    def get_reality(self, session_id):
        if self._projector is not None:
            return self._projector.get_reality(session_id)
        return None

    def invalidate_cache(self, session_id=None) -> None:
        if self._projector is not None:
            self._projector.invalidate_cache(session_id)
