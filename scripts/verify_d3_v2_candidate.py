"""Verify the D3-v2 pre-freeze verification manifest against the checked-out bytes.

CI infrastructure (Category C), not methodology. It exists so a verification run cannot report results for different
bytes than the ones the manifest names. It reads only the files listed in the manifest; it never opens experiment
result rows and never executes methodology code.

Exit codes: 0 all three categories match; 1 any mismatch, missing file or malformed manifest (fail closed).

Usage:
  python scripts/verify_d3_v2_candidate.py [--manifest PATH] [--report PATH] [--commit SHA]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "benchmark" / "analysis" / "D3_V2_VERIFICATION_MANIFEST.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(manifest_path: Path, commit: str) -> dict:
    result: dict = {"manifest": manifest_path.relative_to(ROOT).as_posix(),
                    "manifest_sha256": sha256_file(manifest_path) if manifest_path.is_file() else None,
                    "commit": commit, "categories": {}, "errors": []}
    if not manifest_path.is_file():
        result["errors"].append(f"manifest missing: {manifest_path}")
        result["passed"] = False
        return result
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        categories = manifest["categories"]
    except (ValueError, KeyError) as exc:
        result["errors"].append(f"manifest unreadable: {type(exc).__name__}: {exc}")
        result["passed"] = False
        return result

    for category, body in categories.items():
        files = body.get("files") or {}
        if not files:
            result["errors"].append(f"{category}: no files recorded")
        entries = {}
        for rel, expected in sorted(files.items()):
            path = ROOT / rel
            if not path.is_file():
                result["errors"].append(f"{category}: {rel} is recorded but missing")
                entries[rel] = {"expected": expected, "actual": None, "match": False}
                continue
            actual = sha256_file(path)
            match = actual == expected
            if not match:
                result["errors"].append(f"{category}: {rel} sha256 {actual[:12]} != recorded {expected[:12]}")
            entries[rel] = {"expected": expected, "actual": actual, "match": match}
        result["categories"][category] = entries
    result["passed"] = not result["errors"]
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--commit", default="")
    args = parser.parse_args(argv)

    result = check(args.manifest, args.commit)
    text = json.dumps(result, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    for category, entries in result["categories"].items():
        for rel, entry in entries.items():
            print(f"{'OK  ' if entry['match'] else 'FAIL'} {category:24s} {rel}")
    for error in result["errors"]:
        print(f"ERROR {error}", file=sys.stderr)
    print("D3-V2 CANDIDATE MANIFEST:", "OK" if result["passed"] else "MISMATCH")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
