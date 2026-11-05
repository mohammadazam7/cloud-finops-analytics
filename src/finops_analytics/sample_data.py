"""Download the FinOps Foundation FOCUS sample data at a pinned commit.

The sample is published under CC BY 4.0 by the FinOps Foundation in
github.com/FinOps-Open-Cost-and-Usage-Spec/FOCUS-Sample-Data. It is downloaded rather
than committed, and pinned to a commit with a known checksum so every run analyses the
same bytes.
"""

from __future__ import annotations

import hashlib
import logging
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

REPO = "FinOps-Open-Cost-and-Usage-Spec/FOCUS-Sample-Data"
COMMIT = "adbdd17a132984d6e8583c149c236d2199c3f5bc"
ATTRIBUTION = (
    "FOCUS sample data by the FinOps Foundation "
    "(https://github.com/FinOps-Open-Cost-and-Usage-Spec/FOCUS-Sample-Data), CC BY 4.0"
)


@dataclass(frozen=True, slots=True)
class SampleFile:
    path: str
    sha256: str

    @property
    def url(self) -> str:
        return f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/{self.path}"


SAMPLE_100K = SampleFile(
    "FOCUS-1.0/focus_sample_100000.csv.gz",
    "76e9158659d40cdef0fecfe6fbc8b874a438ef9fb440205b9190ed1600bf6f8a",
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class ChecksumError(RuntimeError):
    pass


def download(sample: SampleFile, dest_dir: Path, *, timeout: float = 60.0) -> Path:
    """Fetch ``sample`` into ``dest_dir`` unless a verified copy is already there."""
    dest = dest_dir / Path(sample.path).name
    if dest.exists() and sha256(dest) == sample.sha256:
        log.info("using cached %s", dest)
        return dest
    dest_dir.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    log.info("downloading %s", sample.url)
    with urllib.request.urlopen(sample.url, timeout=timeout) as resp, tmp.open("wb") as out:
        while block := resp.read(1 << 20):
            out.write(block)
    digest = sha256(tmp)
    if digest != sample.sha256:
        tmp.unlink()
        raise ChecksumError(f"{sample.path}: expected {sample.sha256}, got {digest}")
    os.replace(tmp, dest)
    return dest
