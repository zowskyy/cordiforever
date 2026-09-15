from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .errors import ToolError

EscalationReason = Literal["repeated_failed_call", "repeat_retry_unavailable", "truncated_output", "completion_prerequisites_unmet", "unsupported_declaration",
                           "completion_after_failed_mutation"]


@dataclass(frozen=True)
class EscalationOutcome:
    """Typed hand-off to the coordinator. The agent loop never picks another model itself."""

    reason: EscalationReason
    model: str
    round: int
    mutation_version: int
    repeated_calls: list[str]
    retry_temperature: float | None
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EscalationRequired(ToolError):
    def __init__(self, outcome: EscalationOutcome) -> None:
        super().__init__(f"Escalation required: {outcome.reason} ({', '.join(outcome.repeated_calls)})")
        self.outcome = outcome
