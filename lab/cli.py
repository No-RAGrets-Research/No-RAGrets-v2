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


def cmd_run(args):
    from lab import ir, manifest, runners

    if args.runner not in runners.RUNNERS:
        raise SystemExit(f"unknown runner {args.runner!r}; have: {', '.join(sorted(runners.RUNNERS))}")

    check = manifest.verify()
    if not check["ok"]:
        raise SystemExit(
            "corpus does not match corpus.manifest.json "
            f"(missing={check['missing']}, extra={check['extra']}, changed={check['changed']}). "
            "Fix the corpus or rebuild the manifest; a run over a drifted corpus is not comparable."
        )

    entries = manifest.load()
    if args.limit:
        entries = entries[: args.limit]

    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / f"{args.runner}.jsonl"
    done = {}
    if out_path.exists() and not args.force:
        for line in out_path.read_text().splitlines():
            if line.strip():
                record = json.loads(line)
                done[record["paper_id"]] = record

    directory = manifest.corpus_dir()
    written = 0
    with out_path.open("w") as fh:
        for entry in entries:
            paper_id = pathlib.Path(entry["filename"]).stem
            cached = done.get(paper_id)
            if cached and cached["pdf_sha256"] == entry["sha256"] and not args.force:
                fh.write(json.dumps(cached) + "\n")
                continue
            try:
                result = runners.RUNNERS[args.runner](
                    directory / entry["filename"], paper_id, entry["sha256"],
                )
            except Exception as e:
                print(f"FAILED  {paper_id}: {type(e).__name__}: {e}")
                continue
            fh.write(json.dumps(result) + "\n")
            written += 1
            print(f"{args.runner:16} {paper_id:45} {result['wall_seconds']:7.1f}s "
                  f"{len(result['blocks']):5d} blocks {len(result['tables']):3d} tables")

    print(f"wrote {written} fresh results to {out_path}")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m lab")
    sub = parser.add_subparsers(dest="command", required=True)

    m = sub.add_parser("manifest", help="build or verify the corpus manifest")
    m.add_argument("action", choices=["build", "verify"])
    m.set_defaults(func=cmd_manifest)

    r = sub.add_parser("run", help="run one runner over the corpus")
    r.add_argument("runner")
    r.add_argument("--limit", type=int, default=0, help="only the first N papers")
    r.add_argument("--force", action="store_true", help="ignore cached results")
    r.set_defaults(func=cmd_run)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
