import gzip
from pathlib import Path

import pyarrow as pa
import pytest

from finops_analytics.focus import SPEC, check, load_csv, normalise

HEADER = [c.name for c in SPEC]


def _row(**overrides: str) -> dict[str, str]:
    base = {
        "BilledCost": "1.50",
        "EffectiveCost": "1.20",
        "ListCost": "2.00",
        "ContractedCost": "1.50",
        "ConsumedQuantity": "1",
        "PricingQuantity": "1",
        "BillingAccountId": "123",
        "BillingAccountName": "Acme",
        "BillingCurrency": "USD",
        "BillingPeriodStart": "2024-09-01 00:00:00",
        "BillingPeriodEnd": "2024-10-01 00:00:00",
        "ChargePeriodStart": "2024-09-09 05:00:00",
        "ChargePeriodEnd": "2024-09-09 06:00:00",
        "ChargeCategory": "Usage",
        "ChargeClass": "NULL",
        "ChargeFrequency": "Usage-Based",
        "CommitmentDiscountId": "NULL",
        "CommitmentDiscountStatus": "NULL",
        "ProviderName": "AWS",
        "PublisherName": "Amazon Web Services, Inc.",
        "InvoiceIssuerName": "Amazon Web Services, Inc.",
        "RegionId": "us-west-2",
        "ServiceCategory": "Compute",
        "ServiceName": "Amazon Elastic Compute Cloud",
        "SkuId": "SKU1",
        "SubAccountId": "acct-1",
        "SubAccountName": "Team A",
        "ResourceId": "i-1",
    }
    base.update(overrides)
    return base


def _write(path: Path, rows: list[dict[str, str]], gz: bool = False) -> Path:
    def cell(v: str) -> str:
        return v if v == "NULL" else '"' + v.replace('"', '""') + '"'

    text = ",".join(f'"{h}"' for h in HEADER) + "\n"
    text += "".join(",".join(cell(r[h]) for h in HEADER) + "\n" for r in rows)
    if gz:
        path = path.with_suffix(".csv.gz")
        with gzip.open(path, "wt", encoding="utf-8") as f:
            f.write(text)
    else:
        path.write_text(text, encoding="utf-8")
    return path


def test_clean_file_has_no_findings(tmp_path: Path) -> None:
    table = load_csv(_write(tmp_path / "ok.csv", [_row(), _row(BilledCost="0")]))
    assert all(table.schema.field(h).type == pa.string() for h in HEADER)
    assert check(table) == []


def test_gzip_and_null_handling(tmp_path: Path) -> None:
    table = load_csv(_write(tmp_path / "ok.csv", [_row()], gz=True))
    assert table.column("ChargeClass").to_pylist() == [None]


def test_findings_match_real_world_drift(tmp_path: Path) -> None:
    rows = [
        _row(ChargeFrequency="Usage-based"),
        _row(ChargeCategory="usage"),
        _row(CommitmentDiscountId=""),
        _row(BillingCurrency="usd"),
        _row(ChargePeriodEnd="2024-09-09 05:00:00"),
        _row(BilledCost="n/a"),
        _row(ServiceName=""),
    ]
    found = {(f.rule, f.column): f for f in check(load_csv(_write(tmp_path / "bad.csv", rows)))}
    assert found[("allowed_values", "ChargeFrequency")].repairable
    assert found[("allowed_values", "ChargeCategory")].repairable
    assert found[("empty_string_for_null", "CommitmentDiscountId")].repairable
    assert not found[("currency_code", "BillingCurrency")].repairable
    assert found[("charge_period_order", "ChargePeriodEnd")].rows == 1
    assert found[("not_numeric", "BilledCost")].examples == ("n/a",)
    assert not found[("not_null", "ServiceName")].repairable


def test_unknown_enum_value_is_not_repairable(tmp_path: Path) -> None:
    table = load_csv(_write(tmp_path / "x.csv", [_row(ChargeCategory="Refund")]))
    (finding,) = [f for f in check(table) if f.rule == "allowed_values"]
    assert not finding.repairable
    assert "Refund" in str(finding)


def test_missing_column_reported() -> None:
    table = pa.table({"BilledCost": ["1"]})
    rules = {(f.rule, f.column) for f in check(table)}
    assert ("missing_column", "ServiceName") in rules


def test_normalise_repairs_and_types(tmp_path: Path) -> None:
    rows = [_row(ChargeFrequency="Usage-based", CommitmentDiscountId=""), _row(BilledCost="n/a")]
    out = normalise(load_csv(_write(tmp_path / "n.csv", rows)))
    assert out.column("ChargeFrequency").to_pylist() == ["Usage-Based", "Usage-Based"]
    assert out.column("CommitmentDiscountId").to_pylist() == [None, None]
    assert out.column("BilledCost").to_pylist() == [pytest.approx(1.5), None]
    assert out.schema.field("ChargePeriodStart").type == pa.timestamp("s", tz="UTC")
