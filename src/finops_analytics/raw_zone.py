"""Write billing tables to the raw zone as Parquet, with a manifest.

Layout: ``<root>/<table>/<table>.parquet`` plus ``<root>/_manifest.json`` recording where
each table came from, its row count and a SHA-256 per file. Each file is written to a
temporary name and renamed into place, so an interrupted run never leaves a half-written
table that the models would read as valid.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

log = logging.getLogger(__name__)

MANIFEST = "_manifest.json"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write_tables(
    tables: Mapping[str, pa.Table], root: Path, provenance: Mapping[str, Any]
) -> dict[str, Any]:
    """Write ``tables`` under ``root``, merge them into the manifest and return it.

    Tables already listed in the manifest and not passed here are kept, so the FOCUS
    sample and the synthetic history can be loaded by separate commands.
    """
    root.mkdir(parents=True, exist_ok=True)
    path = root / MANIFEST
    manifest: dict[str, Any] = json.loads(path.read_text()) if path.exists() else {"tables": {}}
    for name, table in tables.items():
        target = root / name / f"{name}.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".parquet.tmp")
        pq.write_table(table, tmp, compression="zstd")
        os.replace(tmp, target)
        manifest["tables"][name] = {
            "path": str(target.relative_to(root)),
            "rows": table.num_rows,
            "sha256": _sha256(target),
            "provenance": dict(provenance),
        }
        log.info("wrote %s rows=%d", target, table.num_rows)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def verify(root: Path) -> list[str]:
    """Problems found when checking files against the manifest; empty means consistent."""
    path = root / MANIFEST
    if not path.exists():
        return [f"missing {MANIFEST}"]
    problems = []
    for name, meta in json.loads(path.read_text())["tables"].items():
        file = root / meta["path"]
        if not file.exists():
            problems.append(f"{name}: file missing")
        elif _sha256(file) != meta["sha256"]:
            problems.append(f"{name}: checksum mismatch")
        elif pq.ParquetFile(file).metadata.num_rows != meta["rows"]:
            problems.append(f"{name}: row count mismatch")
    return problems
