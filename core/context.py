from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .calibration import (
    MODEL_PRESETS,
    DEFAULT_PRESET_KEY,
    preset_key_for_model,
    resolve_calibration,
    calibration_from_context,
    REQUIRED_CALIBRATION_KEYS,
    validate_calibration,
)
from .errors import CancelledError
from .events import Event
from .messages import Message

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self, session_id: str = "") -> None:
        self._session_id = session_id
        self._listeners: Dict[str, List[Callable[[Event], None]]] = {}
        self._lock = threading.Lock()

    def on(self, event_type: str, handler: Callable[[Event], None]) -> None:
        with self._lock:
            self._listeners.setdefault(event_type, []).append(handler)

    def off(self, event_type: str, handler: Callable[[Event], None]) -> None:
        with self._lock:
            handlers = self._listeners.get(event_type, [])
            try:
                handlers.remove(handler)
            except ValueError:
                pass

    def emit(self, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
        event = Event(type=event_type, session_id=self._session_id, payload=payload or {})
        with self._lock:
            handlers = list(self._listeners.get(event_type, []))
            wildcards = list(self._listeners.get("*", []))
        for handler in handlers + wildcards:
            try:
                handler(event)
            except Exception as exc:
                logger.exception("EventBus handler for %r failed: %s", event_type, exc)


@dataclass
class Context:
    config: Dict[str, Any] = field(default_factory=dict)
    messages: List[Message] = field(default_factory=list)
    plugins: Dict[str, Any] = field(default_factory=dict)
    _cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    events: EventBus = field(default_factory=lambda: EventBus(session_id=""))
    prompt_injections: List[Message] = field(default_factory=list)

    def append_message(
        self,
        role: str,
        content: str = "",
        *,
        name: Optional[str] = None,
        tool_call_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
    ) -> Message:
        message = Message(
            role=role,
            content=content,
            name=name,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_calls=tool_calls,
        )
        self.messages.append(message)
        return message

    def clear_messages(self) -> None:
        self.messages.clear()

    def config_get(self, key: str, default: Any = None) -> Any:
        if key in self.config:
            return self.config[key]
        return default

    def cancel(self) -> None:
        self._cancel_event.set()

    def reset_cancel(self) -> None:
        self._cancel_event = threading.Event()

    def check_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise CancelledError("Agent run cancelled.")
