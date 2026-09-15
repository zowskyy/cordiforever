class HarnessError(Exception):
    """Base exception for the harness."""


class PluginError(HarnessError):
    """Plugin registration/lifecycle failure."""


class ToolError(HarnessError):
    """Tool execution failure."""


class ModelError(HarnessError):
    """Model/API failure."""


class WorkspaceError(ToolError):
    """Workspace path violation."""


class PolicyRejection(ToolError):
    """A tool call refused by a harness safety policy before execution; not a tool failure."""

    def __init__(self, message: str, reason: str = "policy", details: dict | None = None) -> None:
        super().__init__(message)
        self.reason = reason
        self.details = details or {}


class CancelledError(HarnessError):
    """Agent run was cancelled."""
