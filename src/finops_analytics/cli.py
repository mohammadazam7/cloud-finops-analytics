"""Command-line entry point: ``finops``."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from finops_analytics.focus import check, load_csv
from finops_analytics.sample_data import ATTRIBUTION, SAMPLE_100K, download


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="finops", description="Cloud cost analytics on FOCUS data.")
    sub = p.add_subparsers(dest="command", required=True)
    d = sub.add_parser("download", help="download the pinned FOCUS sample data")
    d.add_argument("--out", type=Path, default=Path("data/focus-sample"))
    c = sub.add_parser("check", help="check a FOCUS CSV file against the specification")
    c.add_argument("path", type=Path)
    c.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero on repairable findings as well as errors",
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.command == "download":
        path = download(SAMPLE_100K, args.out)
        print(f"{path}\n{ATTRIBUTION}")
        return 0
    table = load_csv(args.path)
    findings = check(table)
    for f in findings:
        print(f)
    errors = [f for f in findings if not f.repairable]
    print(
        f"{table.num_rows:,} rows, {len(errors)} errors, {len(findings) - len(errors)} repairable"
    )
    return 1 if errors or (args.strict and findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
