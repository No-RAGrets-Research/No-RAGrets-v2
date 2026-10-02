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

    all_entries = manifest.load()
    entries = all_entries[: args.limit] if args.limit else all_entries

    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / f"{args.runner}.jsonl"
    # Read unconditionally, even under --force: `done` is both the cache lookup
    # AND what keeps papers outside a --limit slice in the file. --force still
    # re-runs everything in the slice, because the cache-hit test below checks it.
    done = {}
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                record = json.loads(line)
                done[record["paper_id"]] = record

    # Keyed on sha256 AND runner_version: a library upgrade (docling bump, OCR
    # engine change) must invalidate the cache instead of silently replaying
    # stale results, which was v1's cache failure.
    current_version = runners.RUNNER_VERSIONS[args.runner]()

    directory = manifest.corpus_dir()
    written = 0
    # Start from every cached record so a --limit run can never shrink the file:
    # only paper_ids in `entries` (the limited slice, or all of them) are
    # touched below; every other cached record rides through untouched.
    output = dict(done)
    for entry in entries:
        paper_id = pathlib.Path(entry["filename"]).stem
        cached = done.get(paper_id)
        if (cached and cached["pdf_sha256"] == entry["sha256"]
                and cached.get("runner_version") == current_version and not args.force):
            continue
        try:
            result = runners.RUNNERS[args.runner](
                directory / entry["filename"], paper_id, entry["sha256"],
            )
        except Exception as e:
            print(f"FAILED  {paper_id}: {type(e).__name__}: {e}")
            continue
        output[paper_id] = result
        written += 1
        print(f"{args.runner:16} {paper_id:45} {result['wall_seconds']:7.1f}s "
              f"{len(result['blocks']):5d} blocks {len(result['tables']):3d} tables")

    with out_path.open("w") as fh:
        for record in output.values():
            fh.write(json.dumps(record) + "\n")

    print(f"wrote {written} fresh results to {out_path}")
    return 0


def cmd_compare(args):
    from lab import report

    scored = report.write(floor=args.floor)
    print(f"wrote {report.REPORT_PATH}")
    for runner, summary in scored["runners"].items():
        rate = summary["arithmetic"]["pass_rate"]
        rate_text = "—" if rate is None else f"{rate:.3f}"
        print(f"  {runner:16} {summary['papers']:3d} papers  "
              f"arith {summary['arithmetic']['checked']:4d} checked, pass {rate_text}  "
              f"dropped pages {summary['coverage']['dropped_page_count']}")
    return 0


def cmd_import_baseline(args):
    """Import DoclingDocument JSON produced earlier by a bare DocumentConverter."""
    from lab import manifest, runners

    source = pathlib.Path(args.directory).expanduser()
    entries = manifest.load()
    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / "docling-default.jsonl"

    written = skipped = 0
    with out_path.open("w") as fh:
        for entry in entries:
            stem = pathlib.Path(entry["filename"]).stem
            json_path = source / f"{stem}.json"
            if not json_path.exists():
                print(f"MISSING  {stem}.json")
                skipped += 1
                continue
            record = runners.import_docling_json(json_path, stem, entry["sha256"])
            fh.write(json.dumps(record) + "\n")
            written += 1

    print(f"imported {written} baselines to {out_path} ({skipped} missing)")
    return 0 if skipped == 0 else 1


def cmd_export(args):
    """Write a reader bundle from one runner's results."""
    from lab import export, manifest

    results_path = RESULTS_DIR / f"{args.runner}.jsonl"
    if not results_path.exists():
        raise SystemExit(f"{results_path} not found — run: python -m lab run {args.runner}")
    records = [json.loads(line) for line in results_path.read_text().splitlines() if line.strip()]

    written = export.write_bundle(
        records, manifest.load(), pathlib.Path(args.out), manifest.corpus_dir(),
    )
    print(f"wrote {args.out}: {written['counts']['papers']} papers, "
          f"{written['counts']['chunks']} chunks")
    no_regions = sum(1 for c in json.loads((pathlib.Path(args.out) / "chunks.json").read_text())
                     if not c["regions"])
    print(f"  chunks without geometry: {no_regions}")
    if written["missing_pdfs"]:
        print(f"  PDFs not found in the corpus: {len(written['missing_pdfs'])}")

    if args.no_embed:
        print("  --no-embed: vectors.bin left alone, semantic search unavailable")
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

    c = sub.add_parser("compare", help="aggregate results into results/REPORT.md")
    c.add_argument("--floor", default="pdfplumber")
    c.set_defaults(func=cmd_compare)

    i = sub.add_parser("import-baseline", help="import existing DoclingDocument JSON as the baseline")
    i.add_argument("directory", help="e.g. ../No-RAGrets-Master/data/docling_json")
    i.set_defaults(func=cmd_import_baseline)

    e = sub.add_parser("export", help="write a reader bundle from a runner's results")
    e.add_argument("runner")
    e.add_argument("--out", required=True, help="e.g. bundles/no-ragrets-47")
    e.add_argument("--no-embed", action="store_true", help="skip embeddings")
    e.set_defaults(func=cmd_export)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
