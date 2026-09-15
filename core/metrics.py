from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class TokenUsage:
    """Real token usage from a model response."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    prompt_eval_count: int = 0  # Ollama-specific: tokens in prompt
    eval_count: int = 0  # Ollama-specific: tokens generated

    def __post_init__(self) -> None:
        if self.total_tokens == 0:
            self.total_tokens = self.input_tokens + self.output_tokens
        if self.input_tokens == 0 and self.prompt_eval_count > 0:
            self.input_tokens = self.prompt_eval_count
        if self.output_tokens == 0 and self.eval_count > 0:
            self.output_tokens = self.eval_count
        if self.total_tokens == 0:
            self.total_tokens = self.input_tokens + self.output_tokens


@dataclass
class TokenBreakdown:
    """Token cost breakdown for a single agent round."""
    guidance_tokens: int = 0
    tool_schema_tokens: int = 0
    tool_result_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def __post_init__(self) -> None:
        if self.total_tokens == 0:
            self.total_tokens = (
                self.guidance_tokens
                + self.tool_schema_tokens
                + self.tool_result_tokens
                + self.input_tokens
                + self.output_tokens
            )


@dataclass
class RoundMetrics:
    """Metrics for a single agent round."""
    round_index: int
    tool_calls: int = 0
    duplicate_tool_calls: int = 0
    retries: int = 0
    replan: bool = False
    token_usage: Optional[TokenUsage] = None
    token_breakdown: Optional[TokenBreakdown] = None
    files_changed: list[str] = field(default_factory=list)
    success: bool = False
    error: Optional[str] = None
    elapsed_ms: float = 0.0


@dataclass
class TaskMetrics:
    """Aggregate metrics for a complete agent task."""
    task_id: str
    model: str = ""
    profile: str = "lite"
    success: bool = False
    validation_status: str = "unknown"
    rounds: list[RoundMetrics] = field(default_factory=list)
    total_elapsed_seconds: float = 0.0

    @property
    def round_count(self) -> int:
        return len(self.rounds)

    @property
    def tool_call_count(self) -> int:
        return sum(r.tool_calls for r in self.rounds)

    @property
    def duplicate_tool_call_count(self) -> int:
        return sum(r.duplicate_tool_calls for r in self.rounds)

    @property
    def retry_count(self) -> int:
        return sum(r.retries for r in self.rounds)

    @property
    def replan_count(self) -> int:
        return sum(1 for r in self.rounds if r.replan)

    @property
    def files_changed(self) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for r in self.rounds:
            for f in r.files_changed:
                if f not in seen:
                    seen.add(f)
                    result.append(f)
        return result

    @property
    def total_tokens(self) -> int:
        return sum(
            (r.token_usage.total_tokens if r.token_usage else 0)
            for r in self.rounds
        )

    @property
    def input_tokens(self) -> int:
        return sum(
            (r.token_usage.input_tokens if r.token_usage else 0)
            for r in self.rounds
        )

    @property
    def output_tokens(self) -> int:
        return sum(
            (r.token_usage.output_tokens if r.token_usage else 0)
            for r in self.rounds
        )

    @property
    def guidance_tokens(self) -> int:
        return sum(
            (r.token_breakdown.guidance_tokens if r.token_breakdown else 0)
            for r in self.rounds
        )

    @property
    def tool_schema_tokens(self) -> int:
        return sum(
            (r.token_breakdown.tool_schema_tokens if r.token_breakdown else 0)
            for r in self.rounds
        )

    @property
    def tool_result_tokens(self) -> int:
        return sum(
            (r.token_breakdown.tool_result_tokens if r.token_breakdown else 0)
            for r in self.rounds
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "model": self.model,
            "profile": self.profile,
            "success": self.success,
            "validation_status": self.validation_status,
            "total_tokens": self.total_tokens,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "guidance_tokens": self.guidance_tokens,
            "tool_schema_tokens": self.tool_schema_tokens,
            "tool_result_tokens": self.tool_result_tokens,
            "round_count": self.round_count,
            "tool_call_count": self.tool_call_count,
            "duplicate_tool_call_count": self.duplicate_tool_call_count,
            "retry_count": self.retry_count,
            "replan_count": self.replan_count,
            "files_changed": self.files_changed,
            "elapsed_seconds": round(self.total_elapsed_seconds, 3),
        }
