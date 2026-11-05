import json
from pathlib import Path

from finops_analytics import raw_zone
from finops_analytics.cli import main


def test_cli_writes_and_verifies_the_raw_zone(tmp_path: Path) -> None:
    out = tmp_path / "raw"
    assert main(["synthesize", "--out", str(out), "--days", "60"]) == 0
    manifest = json.loads((out / raw_zone.MANIFEST).read_text())
    assert manifest["tables"]["synthetic_charges"]["provenance"]["synthetic"] is True
    assert main(["verify", "--out", str(out)]) == 0
    (out / "synthetic_anomalies" / "synthetic_anomalies.parquet").write_bytes(b"x")
    assert main(["verify", "--out", str(out)]) == 1
    assert raw_zone.verify(tmp_path / "empty") == [f"missing {raw_zone.MANIFEST}"]
