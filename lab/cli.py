"""python -m lab manifest build|verify | run <runner> | compare"""
import argparse
import json
import pathlib
import sys

RESULTS_DIR = pathlib.Path("results")


def cmd_manifest(args):
    from lab import manifest

    if args.action == "build":
        entries = manifest.build()
        scanned = sum(1 for e in entries if e["scanned"])
        print(f"wrote {manifest.MANIFEST_PATH} — {len(entries)} papers, {scanned} look scanned")
        return 0

    result = manifest.verify()
    for label in ("missing", "extra", "changed"):
        for name in result[label]:
            print(f"{label.upper():8} {name}")
    print("manifest ok" if result["ok"] else "manifest does NOT match the corpus")
    return 0 if result["ok"] else 1


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m lab")
    sub = parser.add_subparsers(dest="command", required=True)

    m = sub.add_parser("manifest", help="build or verify the corpus manifest")
    m.add_argument("action", choices=["build", "verify"])
    m.set_defaults(func=cmd_manifest)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
