"""MV-02A workload child (generic). Timed with time.perf_counter() after imports (spec v2.1 §4)."""
import argparse
import json
import sys
import time


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, required=True)
    parser.add_argument("--result-file", required=True)
    args = parser.parse_args(argv)
    t0 = time.perf_counter()
    buffer = bytearray(16 * 1024 * 1024)
    for offset in range(0, len(buffer), 4096):
        buffer[offset] = 1
    total = 0
    for i in range(args.iterations):
        total = (total + i * i) % 1_000_003
    t1 = time.perf_counter()
    document = json.dumps({"child_seconds": t1 - t0, "child_seconds_rounded": round(t1 - t0, 1),
                           "iterations": args.iterations, "checksum": total})
    print(document)
    # The frozen run_monitored captures and discards stdout, so both arms read the same JSON from this file,
    # written after t1 (outside the timed window).
    with open(args.result_file, "w", encoding="utf-8") as handle:
        handle.write(document + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
