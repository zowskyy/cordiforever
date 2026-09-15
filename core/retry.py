from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class RetryPolicy:
    """Configuration for retry with exponential backoff."""

    max_retries: int = 3
    base_delay: float = 0.01
    max_delay: float = 60.0
    jitter: float = 0.0
    backoff_formula: str = "exponential"


def retry_with_backoff(
    func: Callable[..., Any],
    *args,
    policy: Optional[RetryPolicy] = None,
    should_retry: Optional[Callable[[Exception], bool]] = None,
    **kwargs,
) -> Any:
    """Execute func with retry and exponential backoff.

    Args:
        func: Callable to execute.
        *args: Positional arguments for func.
        policy: Retry configuration.
        should_retry: Optional predicate returning True if an exception is
            retryable. When None, all exceptions are retried.
        **kwargs: Keyword arguments for func.

    Returns:
        Result of func on success.

    Raises:
        Last exception if all retries are exhausted or should_retry returns
        False.
    """
    policy = policy or RetryPolicy()
    last_exc: Optional[BaseException] = None

    for attempt in range(1 + policy.max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt >= policy.max_retries:
                break
            if should_retry is not None and not should_retry(exc):
                break
            delay = _compute_delay(policy, attempt)
            time.sleep(delay)

    assert last_exc is not None
    raise last_exc


def _compute_delay(policy: RetryPolicy, attempt: int) -> float:
    if policy.backoff_formula == "exponential":
        delay = policy.base_delay * (2 ** attempt)
    else:
        delay = policy.base_delay * (attempt + 1)
    delay = min(delay, policy.max_delay)
    if policy.jitter > 0:
        delay += random.uniform(0, policy.jitter)
    return delay
