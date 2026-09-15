#!/usr/bin/env python3
"""Swap the active model used by the agent.

Updates the MODEL_PRESETS dictionary in core/context.py to point to
the new model's calibration values. This is a calibration exercise,
not a code change — the calibration table is the source of truth.

Usage:
    python scripts/swap_model.py --model-path /path/to/finetuned/model --config-file core/context.py
    python scripts/swap_model.py --model-path /path/to/finetuned/model --preset-key qwen2.5-coder-1.5b-finetuned
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path


# Default calibration values for a fine-tuned Qwen 1.5B model
# These should be re-measured using scripts/capacity_calculator.py --verify
# but we provide sensible defaults based on the existing 1.5B calibration.
DEFAULT_CALIBRATION = {
    "pruner_budget": 3000,
    "max_messages": 64,
    "max_tool_result_bytes": 4000,
    "rounds_per_file": 1.3,
    "token_safety": 1000,
    "context_window": 32768,
}


def swap_model(model_path: str, config_file: str, preset_key: str = None) -> bool:
    """Update the calibration config to use the new model.

    Args:
        model_path: Path to the new model.
        config_file: Path to the config file (default: core/context.py).
        preset_key: Optional custom preset key.

    Returns:
        True if successful, False otherwise.
    """
    config_path = Path(config_file)
    if not config_path.exists():
        print(f"Config file not found: {config_file}")
        return False

    model_path = Path(model_path).resolve()
    if not model_path.exists():
        print(f"Model path not found: {model_path}")
        return False

    # Use preset_key or derive from model path
    if preset_key is None:
        preset_key = model_path.name

    print(f"Swapping model to: {model_path}")
    print(f"Preset key: {preset_key}")
    print(f"Config file: {config_path}")

    # Read existing config
    content = config_path.read_text(encoding="utf-8")

    # Check if preset already exists
    pattern = re.compile(
        r'^(\s*)"([^"]+)":\s*ModelPreset\([^)]*\)\s*$',
        re.MULTILINE,
    )
    matches = list(pattern.finditer(content))
    existing_keys = [m.group(2) for m in matches]

    if preset_key in existing_keys:
        print(f"Preset '{preset_key}' already exists. Overwriting.")

    # Build the new preset entry
    # We need to find the MODEL_PRESETS dict and add/update the entry
    # For now, we'll add it after the last ModelPreset entry

    new_entry = f'''    "{preset_key}": ModelPreset(
        model=f"local:{model_path}",
        pruner_budget={DEFAULT_CALIBRATION["pruner_budget"]},
        max_messages={DEFAULT_CALIBRATION["max_messages"]},
        max_tool_result_bytes={DEFAULT_CALIBRATION["max_tool_result_bytes"]},
        rounds_per_file={DEFAULT_CALIBRATION["rounds_per_file"]},
        token_safety={DEFAULT_CALIBRATION["token_safety"]},
        context_window={DEFAULT_CALIBRATION["context_window"]},
    ),'''

    # Find the MODEL_PRESETS dictionary and insert/update the entry
    # Look for the last entry in MODEL_PRESETS
    lines = content.split('\n')
    new_lines = []
    in_model_presets = False
    preset_start_indent = None
    last_preset_end = None
    preset_indent = None

    for i, line in enumerate(lines):
        # Check if we're entering MODEL_PRESETS
        if 'MODEL_PRESETS' in line and '=' in line:
            in_model_presets = True
            continue

        # Check if we're exiting (closing brace at same or lower indent)
        if in_model_presets:
            # Look for the closing of MODEL_PRESETS dict
            stripped = line.strip()
            if stripped == '}' and not line.strip().startswith('"'):
                # This might be the end of MODEL_PRESETS
                # Insert our new entry before the closing brace
                # Match the indentation of existing entries
                indent_match = re.match(r'^(\s+)"', lines[i-1] if i > 0 else "")
                if indent_match:
                    indent = indent_match.group(1)
                else:
                    indent = "    "

                new_lines.append(f'    "{preset_key}": ModelPreset(')
                new_lines.append(f'        model=f"local:{model_path}",')
                new_lines.append(f'        pruner_budget={DEFAULT_CALIBRATION["pruner_budget"]},')
                new_lines.append(f'        max_messages={DEFAULT_CALIBRATION["max_messages"]},')
                new_lines.append(f'        max_tool_result_bytes={DEFAULT_CALIBRATION["max_tool_result_bytes"]},')
                new_lines.append(f'        rounds_per_file={DEFAULT_CALIBRATION["rounds_per_file"]},')
                new_lines.append(f'        token_safety={DEFAULT_CALIBRATION["token_safety"]},')
                new_lines.append(f'        context_window={DEFAULT_CALIBRATION["context_window"]},')
                new_lines.append(f'    ),')
                in_model_presets = False
                continue

        new_lines.append(line)

    # Fallback: if we didn't find the closing brace pattern, try a simpler approach
    if preset_key not in '\n'.join(new_lines) and '"qwen2.5-coder:1.5b"' in content:
        # Find the 1.5B preset and add after it
        new_content = re.sub(
            r'("qwen2\.5-coder:1\.5b":\s*ModelPreset\([^)]*\),)',
            r'\1\n' + new_entry.strip(),
            content,
            flags=re.DOTALL,
        )
        if new_content != content:
            config_path.write_text(new_content, encoding="utf-8")
            print(f"Added preset '{preset_key}' to {config_path}")
            return True

    # Final approach: just append before the closing brace of MODEL_PRESETS
    final_content = '\n'.join(new_lines)
    if preset_key not in final_content:
        # Use regex to add before the last `}` that closes MODEL_PRESETS
        final_content = re.sub(
            r'(MODEL_PRESETS\s*=\s*\{)',
            r'\1\n' + new_entry,
            final_content,
            flags=re.DOTALL,
            count=1,
        )

    config_path.write_text(final_content, encoding="utf-8")
    print(f"Added preset '{preset_key}' to {config_path}")
    print("\nNote: You should re-measure calibration using:")
    print(f"  python scripts/capacity_calculator.py --verify --model {model_path}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Swap the active model and update calibration presets"
    )
    parser.add_argument(
        "--model-path",
        required=True,
        help="Path to the new model directory",
    )
    parser.add_argument(
        "--config-file",
        default="core/context.py",
        help="Config file to update (default: core/context.py)",
    )
    parser.add_argument(
        "--preset-key",
        default=None,
        help="Custom preset key (default: derived from model path)",
    )
    args = parser.parse_args()

    if swap_model(args.model_path, args.config_file, args.preset_key):
        print("Model swap complete.")
        return 0
    else:
        print("Model swap failed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
