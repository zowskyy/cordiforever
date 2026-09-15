from __future__ import annotations

from core.recovery import RecoveryManager
from core.plugin import Plugin


class RecoveryManagerPlugin(Plugin):
    name = "recovery_manager"
    dependencies = ("event_logger",)

    def __init__(self) -> None:
        super().__init__()
        self._manager = None

    def register(self, context) -> None:
        super().register(context)
        event_log = context.plugins.get("event_log")
        if event_log is not None:
            self._manager = RecoveryManager(event_log)

    def start(self) -> None:
        pass

    def wake(self, session_id):
        if self._manager is not None:
            return self._manager.wake(session_id)
        from core.recovery import RecoveryAction
        return RecoveryAction(action="step")

    def get_active_sessions(self):
        if self._manager is not None:
            return self._manager.get_active_sessions()
        return []
