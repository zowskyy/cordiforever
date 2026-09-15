from __future__ import annotations

import re
from typing import Any, Dict, Optional


MODEL_PRESETS: Dict[str, Dict[str, Any]] = {
    # Context length verified via `ollama show gemma3:1b` (32768); other limits mirror the 32k 1.5b preset until re-measured.
    # sampling + constrained_actions chosen by benchmark/tool_call_eval.py (first-step accuracy 3.3% -> 86.7% on 30 tasks).
    "1b": {"label": "gemma3:1b (32k)", "max_tokens": 32768, "pruner_budget": 30000, "safety": 0.85, "max_messages": 200, "rounds_per_file": 1.05, "max_tool_result_bytes": 65536,
           # num_predict bounds runaway generation (reproduced: 1 in 6 "Write the docs" samples looped past 3.7k tokens).
           "sampling": {"temperature": 0.0, "num_predict": 2048}, "constrained_actions": True, "require_read_before_write": True,
           "repeat_retry_temperature": 0.4,
           # Enabled for safety, not credited as a capability improvement: frozen corpus stray files 4->0,
           # false "done" 4->0, rounds flat, task success unchanged at 3/10 (EXPERIMENT_LOG.md "Wrong-path guard experiment", 2026-09-13).
           "require_known_paths": True,
           # Completion invariant: a request that names an existing file cannot finish before that file was read.
           "require_read_named_files": True,
           # Keyword-triggered array hints misfired on unrelated tasks and were echoed as answers (2026-09-13).
           "array_guidance": False},
    "1.5b": {"label": "qwen2.5-coder:1.5b (33k)", "max_tokens": 32768, "pruner_budget": 30000, "safety": 0.85, "max_messages": 200, "rounds_per_file": 1.05, "max_tool_result_bytes": 65536},
    "7b": {"label": "qwen2.5-coder:7b (8k, stable)", "max_tokens": 8192, "pruner_budget": 6500, "safety": 0.88, "max_messages": 60, "rounds_per_file": 1.05, "max_tool_result_bytes": 16384},
    "14b": {"label": "qwen2.5-coder:14b (16k)", "max_tokens": 16384, "pruner_budget": 14000, "safety": 0.90, "max_messages": 80, "rounds_per_file": 1.02, "max_tool_result_bytes": 32768},
}
DEFAULT_PRESET_KEY = "1.5b"

_MODEL_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*b$", re.IGNORECASE)


def preset_key_for_model(model_name: str) -> str:
    if not model_name:
        return DEFAULT_PRESET_KEY
    candidate = str(model_name).split(":")[-1].strip().lower()
    if candidate in MODEL_PRESETS:
        return candidate
    m = _MODEL_SIZE_RE.search(candidate)
    if m:
        key = m.group(1) + "b"
        if key in MODEL_PRESETS:
            return key
    return DEFAULT_PRESET_KEY


def resolve_calibration(model_name: str = "", explicit: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    key = preset_key_for_model(model_name)
    cal: Dict[str, Any] = dict(MODEL_PRESETS[key])
    cal["preset"] = key
    if explicit:
        for k, v in explicit.items():
            if v is not None:
                cal[k] = v
    validate_calibration(cal)
    return cal


def calibration_from_context(context: Optional["Context"]) -> Dict[str, Any]:
    if context is None:
        return resolve_calibration()
    cfg = context.config or {}
    explicit = cfg.get("calibration")
    if isinstance(explicit, dict):
        return resolve_calibration(str(cfg.get("model", "")), explicit)
    return resolve_calibration(str(cfg.get("model", "")))


REQUIRED_CALIBRATION_KEYS = {"max_tokens", "pruner_budget", "safety", "max_messages", "rounds_per_file", "max_tool_result_bytes"}


def validate_calibration(cal: Dict[str, Any]) -> None:
    missing = REQUIRED_CALIBRATION_KEYS - cal.keys()
    if missing:
        raise ValueError(f"calibration missing required keys: {missing}")
    if not isinstance(cal["max_tokens"], int) or cal["max_tokens"] <= 0:
        raise ValueError("max_tokens must be a positive int")
    if not isinstance(cal["pruner_budget"], int) or cal["pruner_budget"] <= 0:
        raise ValueError("pruner_budget must be a positive int")
    if not (0 < cal["safety"] <= 1):
        raise ValueError("safety must be in (0, 1]")
    if not isinstance(cal["max_messages"], int) or cal["max_messages"] <= 0:
        raise ValueError("max_messages must be a positive int")
    if not isinstance(cal["rounds_per_file"], (int, float)) or cal["rounds_per_file"] <= 0:
        raise ValueError("rounds_per_file must be a positive number")
    if not isinstance(cal["max_tool_result_bytes"], int) or cal["max_tool_result_bytes"] <= 0:
        raise ValueError("max_tool_result_bytes must be a positive int")
