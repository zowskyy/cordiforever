from __future__ import annotations

from typing import Any, Dict, Optional


class SessionRegistry:
    def __init__(self) -> None:
        self._services: Dict[str, Any] = {}

    def register(self, name: str, service: Any) -> None:
        self._services[name] = service

    def get(self, name: str, default: Any = None) -> Any:
        return self._services.get(name, default)

    def unregister(self, name: str) -> None:
        self._services.pop(name, None)


def get_session_registry(context: Any) -> SessionRegistry:
    registry = getattr(context, "_session_registry", None)
    if registry is None:
        registry = SessionRegistry()
        context._session_registry = registry
    return registry
