#!/usr/bin/env python
"""
Capacity diff — compare two JSON outputs from capacity_calculator.py --json.

Usage:
  python scripts/capacity_calculator.py --model 1.5b --json > before.json
  # change templates/guidance, re-measure
  python scripts/capacity_calculator.py --model 1.5b --json > after.json
  python scripts/capacity_diff.py before.json after.json
"""
from __future__ import annotations

import argparse
import json


def main():
    p = argparse.ArgumentParser(description="Diff two capacity calculator JSON outputs (before vs after).")
    p.add_argument("before", help="JSON output from capacity_calculator.py --json (before)")
    p.add_argument("after", help="JSON output from capacity_calculator.py --json (after)")
    args = p.parse_args()

    with open(args.before, encoding="utf-8-sig") as f:
        before = json.load(f)
    with open(args.after, encoding="utf-8-sig") as f:
        after = json.load(f)

    before_by_name = {r["name"]: r for r in before["results"]}
    after_by_name = {r["name"]: r for r in after["results"]}

    common = set(before_by_name) & set(after_by_name)
    if not common:
        print("No matching configs to compare")
        return

    print(f"Capacity diff: {before['model']}")
    print(f"{'Config':<36} {'Dfiles':>8} {'Dtokens':>9} {'Dmsgs':>7} {'Drounds':>8} {'Hint':<40}")
    print("-" * 118)

    for name in sorted(common):
        b = before_by_name[name]
        a = after_by_name[name]
        d_files = a["max_files"] - b["max_files"]
        d_tokens = a["tokens_at_max"] - b["tokens_at_max"]
        d_msgs = a["messages_at_max"] - b["messages_at_max"]
        d_rounds = a["recommended_rounds"] - b["recommended_rounds"]

        hint = ""
        if d_files < 0:
            hint = f"Cut guidance ~{abs(d_files)*3} or per_file ~{abs(d_files)*5} to recover"
        elif d_files > 0:
            hint = f"Can add ~{d_files*2} tokens guidance or +{d_files} files"

        print(f"{name:<36} {d_files:>8} {d_tokens:>9} {d_msgs:>7} {d_rounds:>8} {hint:<40}")


if __name__ == "__main__":
    main()
