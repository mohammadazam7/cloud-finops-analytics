"""Load FOCUS billing exports and check them against the specification.

FOCUS (FinOps Open Cost and Usage Specification) defines common column names, types and
allowed values for cloud billing data. Real exports drift from it: providers spell
enumerations differently, write empty strings where the specification requires null,
and occasionally leave mandatory columns empty. Every downstream number depends on these
columns, so the drift is measured and repaired explicitly instead of absorbed silently.

The rules here cover the subset of FOCUS 1.0 that this project reads. Each rule reports
the number of rows that break it and a few example values, and :func:`normalise` applies
only repairs that are unambiguous (case of an enumeration value, empty string to null).
Anything else is left for the caller to decide on.
"""

from __future__ import annotations

import csv
import gzip
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv


class Kind(Enum):
    STRING = "string"
    DECIMAL = "decimal"
    DATETIME = "datetime"


@dataclass(frozen=True, slots=True)
class Column:
    name: str
    kind: Kind
    not_null: bool = False
    allowed: frozenset[str] | None = None


def _enum(*values: str) -> frozenset[str]:
    return frozenset(values)


SPEC: tuple[Column, ...] = (
    Column("BilledCost", Kind.DECIMAL, not_null=True),
    Column("EffectiveCost", Kind.DECIMAL, not_null=True),
    Column("ListCost", Kind.DECIMAL, not_null=True),
    Column("ContractedCost", Kind.DECIMAL),
    Column("ConsumedQuantity", Kind.DECIMAL),
    Column("PricingQuantity", Kind.DECIMAL),
    Column("BillingAccountId", Kind.STRING, not_null=True),
    Column("BillingAccountName", Kind.STRING),
    Column("BillingCurrency", Kind.STRING, not_null=True),
    Column("BillingPeriodStart", Kind.DATETIME, not_null=True),
    Column("BillingPeriodEnd", Kind.DATETIME, not_null=True),
    Column("ChargePeriodStart", Kind.DATETIME, not_null=True),
    Column("ChargePeriodEnd", Kind.DATETIME, not_null=True),
    Column(
        "ChargeCategory",
        Kind.STRING,
        not_null=True,
        allowed=_enum("Usage", "Purchase", "Tax", "Credit", "Adjustment"),
    ),
    Column("ChargeClass", Kind.STRING, allowed=_enum("Correction")),
    Column("ChargeFrequency", Kind.STRING, allowed=_enum("One-Time", "Recurring", "Usage-Based")),
    Column("CommitmentDiscountId", Kind.STRING),
    Column("CommitmentDiscountStatus", Kind.STRING, allowed=_enum("Used", "Unused")),
    Column("ProviderName", Kind.STRING, not_null=True),
    Column("PublisherName", Kind.STRING, not_null=True),
    Column("InvoiceIssuerName", Kind.STRING, not_null=True),
    Column("RegionId", Kind.STRING),
    Column("ServiceCategory", Kind.STRING, not_null=True),
    Column("ServiceName", Kind.STRING, not_null=True),
    Column("SkuId", Kind.STRING),
    Column("SubAccountId", Kind.STRING),
    Column("SubAccountName", Kind.STRING),
    Column("ResourceId", Kind.STRING),
)

_CURRENCY = re.compile(r"^[A-Z]{3}$")
_NUMBER = r"^-?\d+(\.\d+)?([eE][-+]?\d+)?$"
_TIMESTAMP = pa.timestamp("s", tz="UTC")


@dataclass(frozen=True, slots=True)
class Finding:
    rule: str
    column: str
    rows: int
    examples: tuple[str, ...]
    repairable: bool

    def __str__(self) -> str:
        tag = "repairable" if self.repairable else "error"
        shown = ", ".join(repr(e) for e in self.examples)
        return f"[{tag}] {self.rule} {self.column}: {self.rows} rows (e.g. {shown})"


def load_csv(path: Path) -> pa.Table:
    """Read a FOCUS CSV (optionally gzip-compressed) with every column as text.

    Types are applied by :func:`normalise` after conformance is checked, so a malformed
    value is reported against its rule rather than failing the whole read.
    """
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", newline="", encoding="utf-8") as f:
        header = next(csv.reader(f))
    opts = pacsv.ConvertOptions(
        column_types={name: pa.string() for name in header},
        null_values=["NULL"],
        strings_can_be_null=True,
        quoted_strings_can_be_null=False,
    )
    return pacsv.read_csv(path, convert_options=opts)


def _examples(values: pa.ChunkedArray, mask: pa.ChunkedArray, k: int = 3) -> tuple[str, ...]:
    picked = pc.unique(pc.filter(values, mask)).to_pylist()[:k]
    return tuple("<null>" if v is None else str(v) for v in picked)


def _casefold_map(allowed: frozenset[str]) -> Mapping[str, str]:
    return {v.casefold(): v for v in allowed}


def check(table: pa.Table, spec: tuple[Column, ...] = SPEC) -> list[Finding]:
    """Every rule the table breaks, in spec order. An empty list means conformant."""
    findings: list[Finding] = []
    names = set(table.column_names)
    for col in spec:
        if col.name not in names:
            findings.append(Finding("missing_column", col.name, table.num_rows, (), False))
            continue
        values = table.column(col.name)
        is_null = pc.is_null(values)
        is_empty = pc.fill_null(pc.equal(values, ""), False)

        if col.not_null:
            mask = pc.or_(is_null, is_empty)
            if (n := pc.sum(mask).as_py() or 0) > 0:
                findings.append(Finding("not_null", col.name, n, _examples(values, mask), False))
        elif (n := pc.sum(is_empty).as_py() or 0) > 0:
            findings.append(
                Finding("empty_string_for_null", col.name, n, _examples(values, is_empty), True)
            )

        present = pc.and_(pc.invert(is_null), pc.invert(is_empty))
        if col.allowed is not None:
            ok = pc.is_in(values, value_set=pa.array(sorted(col.allowed)))
            bad = pc.and_(present, pc.invert(ok))
            if (n := pc.sum(bad).as_py() or 0) > 0:
                folded = _casefold_map(col.allowed)
                bad_values = pc.filter(values, bad).to_pylist()
                fixable = all(str(v).casefold() in folded for v in bad_values)
                findings.append(
                    Finding("allowed_values", col.name, n, _examples(values, bad), fixable)
                )
        if col.kind is Kind.DECIMAL:
            numeric = pc.fill_null(pc.match_substring_regex(values, _NUMBER), False)
            bad = pc.and_(present, pc.invert(numeric))
            if (n := pc.sum(bad).as_py() or 0) > 0:
                findings.append(Finding("not_numeric", col.name, n, _examples(values, bad), False))
        if col.kind is Kind.DATETIME:
            parsed = pc.strptime(
                pc.if_else(present, values, None), "%Y-%m-%d %H:%M:%S", "s", error_is_null=True
            )
            bad = pc.and_(present, pc.is_null(parsed))
            if (n := pc.sum(bad).as_py() or 0) > 0:
                findings.append(Finding("not_datetime", col.name, n, _examples(values, bad), False))

    if "BillingCurrency" in names:
        cur = table.column("BillingCurrency")
        bad = pc.and_(
            pc.invert(pc.is_null(cur)),
            pc.invert(pc.match_substring_regex(cur, _CURRENCY.pattern)),
        )
        if (n := pc.sum(bad).as_py() or 0) > 0:
            findings.append(
                Finding("currency_code", "BillingCurrency", n, _examples(cur, bad), False)
            )
    if {"ChargePeriodStart", "ChargePeriodEnd"} <= names:
        start = pc.strptime(
            table["ChargePeriodStart"], "%Y-%m-%d %H:%M:%S", "s", error_is_null=True
        )
        end = pc.strptime(table["ChargePeriodEnd"], "%Y-%m-%d %H:%M:%S", "s", error_is_null=True)
        bad = pc.fill_null(pc.less_equal(end, start), False)
        if (n := pc.sum(bad).as_py() or 0) > 0:
            findings.append(
                Finding(
                    "charge_period_order",
                    "ChargePeriodEnd",
                    n,
                    _examples(table["ChargePeriodEnd"], bad),
                    False,
                )
            )
    return findings


def normalise(table: pa.Table, spec: tuple[Column, ...] = SPEC) -> pa.Table:
    """Apply the unambiguous repairs and cast spec columns to their types.

    Empty strings become null in nullable columns, and enumeration values that differ
    from an allowed value only by case are rewritten to the allowed spelling. Values that
    still do not parse become null; :func:`check` should be run first to see them.
    """
    out = table
    for col in spec:
        if col.name not in out.column_names:
            continue
        idx = out.column_names.index(col.name)
        values = out.column(col.name)
        values = pc.if_else(pc.fill_null(pc.equal(values, ""), False), None, values)
        if col.allowed is not None:
            folded = _casefold_map(col.allowed)
            values = pa.chunked_array(
                [
                    pa.array(
                        [
                            None if v is None else folded.get(v.casefold(), v)
                            for v in chunk.to_pylist()
                        ],
                        type=pa.string(),
                    )
                    for chunk in values.chunks
                ],
                type=pa.string(),
            )
        if col.kind is Kind.DECIMAL:
            numeric = pc.fill_null(pc.match_substring_regex(values, _NUMBER), False)
            values = pc.cast(pc.if_else(numeric, values, None), pa.float64())
        elif col.kind is Kind.DATETIME:
            values = pc.assume_timezone(
                pc.strptime(values, "%Y-%m-%d %H:%M:%S", "s", error_is_null=True), "UTC"
            )
        out = out.set_column(idx, col.name, values)
    return out
