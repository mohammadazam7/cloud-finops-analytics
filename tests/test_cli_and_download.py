import gzip
import hashlib
from pathlib import Path
from unittest import mock

import pytest

from finops_analytics import sample_data
from finops_analytics.cli import main
from finops_analytics.sample_data import ChecksumError, SampleFile, download

from .test_focus import _row, _write


class _Resp:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def read(self, n: int) -> bytes:
        out, self.data = self.data[:n], self.data[n:]
        return out

    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def test_download_verifies_and_caches(tmp_path: Path) -> None:
    payload = gzip.compress(b"a,b\n1,2\n")
    sample = SampleFile("dir/x.csv.gz", hashlib.sha256(payload).hexdigest())
    with mock.patch.object(sample_data.urllib.request, "urlopen", return_value=_Resp(payload)) as m:
        path = download(sample, tmp_path)
        assert path.read_bytes() == payload
        download(sample, tmp_path)
    assert m.call_count == 1


def test_download_rejects_wrong_checksum(tmp_path: Path) -> None:
    sample = SampleFile("dir/x.csv.gz", "0" * 64)
    with (
        mock.patch.object(sample_data.urllib.request, "urlopen", return_value=_Resp(b"tampered")),
        pytest.raises(ChecksumError),
    ):
        download(sample, tmp_path)
    assert not list(tmp_path.iterdir())


def test_url_is_pinned_to_a_commit() -> None:
    assert sample_data.COMMIT in sample_data.SAMPLE_100K.url


def test_cli_check_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    clean = _write(tmp_path / "clean.csv", [_row()])
    assert main(["check", str(clean)]) == 0
    repairable = _write(tmp_path / "rep.csv", [_row(ChargeFrequency="Usage-based")])
    assert main(["check", str(repairable)]) == 0
    assert main(["check", "--strict", str(repairable)]) == 1
    broken = _write(tmp_path / "bad.csv", [_row(ServiceName="")])
    assert main(["check", str(broken)]) == 1
    assert "1 errors" in capsys.readouterr().out
