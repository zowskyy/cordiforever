import sys

from textkit import slugify


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    print(slugify(" ".join(args)))


if __name__ == "__main__":
    main()
