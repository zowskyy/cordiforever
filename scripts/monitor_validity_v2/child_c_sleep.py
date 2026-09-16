"""MV-02C child (generic): sleep for a given time, then exit with a given code."""
import argparse
import sys
import time


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--sleep", type=float, required=True)
    parser.add_argument("--exit-code", type=int, default=0)
    args = parser.parse_args(argv)
    time.sleep(args.sleep)
    return args.exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
