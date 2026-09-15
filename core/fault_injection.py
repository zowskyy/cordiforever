from __future__ import annotations

import random
from typing import Any

from core.errors import ToolError


class FaultInjector:
    """Inject failures for recovery testing."""

    @staticmethod
    def inject_timeout(tool_name: str, probability: float = 0.3) -> None:
        if random.random() < probability:
            raise ToolError(f"Simulated timeout for {tool_name}")

    @staticmethod
    def inject_malformed_args(tool_name: str, probability: float = 0.2) -> None:
        if random.random() < probability:
            raise ToolError(f"Simulated malformed args for {tool_name}")

    @staticmethod
    def inject_stale_context(context: Any, probability: float = 0.15) -> None:
        if random.random() < probability:
            if hasattr(context, "clear_messages"):
                context.clear_messages()
            if hasattr(context, "append_message"):
                context.append_message("system", "Context was reset due to stale state.")
