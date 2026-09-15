from __future__ import annotations

from core.persona_memory import PersonaMemory
from core.plugin import EventDrivenPlugin


class PersonaMemoryPlugin(EventDrivenPlugin):
    name = "persona_memory"
    dependencies = ("event_logger",)

    def __init__(self) -> None:
        super().__init__()
        self._persona = None

    def register(self, context) -> None:
        super().register(context)
        event_log = context.plugins.get("event_log")
        if event_log is not None:
            self._persona = PersonaMemory(event_log)

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def on_turn_start(self, event) -> None:
        self._maybe_update_persona(event)

    def _maybe_update_persona(self, event) -> None:
        if self._persona is None:
            return
        payload = event.payload if hasattr(event, "payload") else {}
        user_text = payload.get("user_text", "")
        if not user_text:
            return
        session_id = payload.get("session_id", "default")
        try:
            self._persona.update(session_id, "last_query", user_text, confidence=0.9)
        except Exception:
            pass

    def add_hypothesis(self, session_id, attribute, hypothesis, confidence=0.5, source_event_id=None) -> None:
        if self._persona is not None:
            self._persona.add_hypothesis(session_id, attribute, hypothesis, confidence, source_event_id)

    def reinforce_hypothesis(self, session_id, attribute, hypothesis, evidence_confidence=1.0) -> None:
        if self._persona is not None:
            self._persona.reinforce_hypothesis(session_id, attribute, hypothesis, evidence_confidence)

    def get_hypotheses(self, session_id, attribute=None, min_confidence=0.0):
        if self._persona is not None:
            return self._persona.get_hypotheses(session_id, attribute, min_confidence)
        return []

    def get_best_hypothesis(self, session_id, attribute, min_confidence=0.3):
        if self._persona is not None:
            return self._persona.get_best_hypothesis(session_id, attribute, min_confidence)
        return None

    def get(self, session_id, attribute=None, min_confidence=0.0):
        if self._persona is not None:
            return self._persona.get(session_id, attribute, min_confidence)
        return []

    def get_profile_summary(self, session_id) -> str:
        if self._persona is not None:
            return self._persona.get_profile_summary(session_id)
        return "No persona data available."
