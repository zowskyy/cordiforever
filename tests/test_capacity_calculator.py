from __future__ import annotations

import json

from core.context import MODEL_PRESETS


def test_capacity_calculator_diff_mode():
    """Diff mode prints a human-readable diff between two calibration tables."""
    import io
    import sys

    from scripts.capacity_calculator import main

    left = {
        key: dict(values) for key, values in MODEL_PRESETS.items()
    }
    # Introduce deliberate diffs so the diff mode exercises formatting
    left["1.5b"]["pruner_budget"] = 2999
    left["7b"]["max_messages"] = 59
    right = dict(MODEL_PRESETS)

    sys.argv = ["capacity_calculator.py", "--diff", json.dumps(left), json.dumps(right)]
    captured = io.StringIO()
    sys.stdout = captured
    try:
        main()
    finally:
        sys.stdout = sys.__stdout__

    output = captured.getvalue()
    assert "1.5b" in output
    assert "7b" in output
