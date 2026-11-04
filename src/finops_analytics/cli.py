"""Command-line entry point: ``finops``."""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import logging
from collections.abc import Sequence
from pathlib import Path

from finops_analytics import raw_zone
from finops_analytics.focus import check, load_csv, normalise
from finops_analytics.sample_data import ATTRIBUTION, SAMPLE_100K, download
from finops_analytics.synthetic import SyntheticConfig, generate


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
    ld = sub.add_parser("load-sample", help="normalise the FOCUS sample into the raw zone")
    ld.add_argument("--sample", type=Path, default=Path("data/focus-sample"))
    ld.add_argument("--out", type=Path, default=Path("data/raw"))
    sy = sub.add_parser("synthesize", help="write the seeded synthetic history to the raw zone")
    sy.add_argument("--out", type=Path, default=Path("data/raw"))
    sy.add_argument("--seed", type=int, default=SyntheticConfig.seed)
    sy.add_argument("--start", type=dt.date.fromisoformat, default=SyntheticConfig.start)
    sy.add_argument("--days", type=int, default=SyntheticConfig.days)
    v = sub.add_parser("verify", help="check raw zone files against their manifest")
    v.add_argument("--out", type=Path, default=Path("data/raw"))
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.command == "download":
        path = download(SAMPLE_100K, args.out)
        print(f"{path}\n{ATTRIBUTION}")
        return 0
    if args.command == "load-sample":
        source = download(SAMPLE_100K, args.sample)
        table = normalise(load_csv(source))
        raw_zone.write_tables(
            {"focus_sample": table},
            args.out,
            {"source": SAMPLE_100K.url, "sha256": SAMPLE_100K.sha256, "license": ATTRIBUTION},
        )
        print(f"focus_sample {table.num_rows:,} rows")
        return 0
    if args.command == "synthesize":
        cfg = SyntheticConfig(seed=args.seed, start=args.start, days=args.days)
        billing = generate(cfg)
        provenance = {"synthetic": True} | {k: str(v) for k, v in dataclasses.asdict(cfg).items()}
        raw_zone.write_tables(
            {"synthetic_charges": billing.charges, "synthetic_anomalies": billing.anomalies},
            args.out,
            provenance,
        )
        print(f"synthetic_charges {billing.charges.num_rows:,} rows (synthetic)")
        return 0
    if args.command == "verify":
        problems = raw_zone.verify(args.out)
        for p in problems:
            print(p)
        print("raw zone consistent" if not problems else f"{len(problems)} problem(s)")
        return 1 if problems else 0
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
