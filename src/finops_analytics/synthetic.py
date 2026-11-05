"""Seeded synthetic FOCUS billing history for a multi-account cloud customer.

The public FOCUS sample covers six months and a few hundred dollars, which is too short
for forecasting backtests and too small for commitment planning. This module produces a
longer history in the same FOCUS columns: one row per day, sub-account, service and
region, plus the monthly commitment purchases, unused commitment and tax rows a real
export carries. Every row has ``x_Synthetic = true`` and the data is labelled synthetic
wherever it is shown.

The service catalog (provider, service category, service name and region) is taken from
services that appear in the FOCUS sample. Spend levels, growth and discounts are
assumptions chosen to look like a mid-sized company, and are stated in
:class:`SyntheticConfig`.

Behaviour that later analysis is meant to find is built in and recorded:

* steady growth with a weekly cycle (non-production accounts are quieter at weekends);
* cost anomalies (a service in one account spikes for one to four days), written to a
  separate ground-truth table so anomaly detection can be scored;
* step changes where a workload moves between services, which a forecast must survive;
* a compute savings plan that covers part of the compute usage at a discount, bought
  monthly, so coverage and utilization can be measured.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pyarrow as pa

# (provider, service category, service name, regions, relative weight)
CATALOG: tuple[tuple[str, str, str, tuple[str, ...], float], ...] = (
    ("AWS", "Compute", "Amazon Elastic Compute Cloud",
     ("us-east-1", "us-west-2", "eu-central-1"), 0.34),
    ("AWS", "Compute", "AWS Lambda", ("us-east-1", "us-west-2"), 0.04),
    ("AWS", "Storage", "Amazon Simple Storage Service", ("us-east-1", "us-west-2"), 0.08),
    ("AWS", "Storage", "Amazon Elastic File System", ("us-west-2",), 0.02),
    ("AWS", "Databases", "Amazon Relational Database Service", ("us-east-1", "eu-central-1"), 0.14),
    ("AWS", "Databases", "Amazon DynamoDB", ("us-east-1",), 0.04),
    ("AWS", "Networking", "Elastic Load Balancing", ("us-east-1", "us-west-2"), 0.05),
    ("AWS", "Networking", "Amazon CloudFront", ("us-east-1",), 0.04),
    ("AWS", "Networking", "Amazon Virtual Private Cloud", ("us-east-1", "us-west-2"), 0.03),
    ("AWS", "Management and Governance", "AmazonCloudWatch", ("us-east-1", "us-west-2"), 0.04),
    ("AWS", "Integration", "Amazon Simple Queue Service", ("us-east-1",), 0.01),
    ("AWS", "Security", "Amazon GuardDuty", ("us-east-1",), 0.01),
    ("Microsoft", "Compute", "Virtual Machines", ("eastus", "eastus2"), 0.08),
    ("Microsoft", "Storage", "Storage Accounts", ("eastus",), 0.03),
    ("Microsoft", "AI and Machine Learning", "Azure Machine Learning", ("eastus",), 0.05),
)  # fmt: skip
TEAMS = ("platform", "data", "ml", "web", "payments", "search")
ENVIRONMENTS = ("prod", "staging", "dev")
SAVINGS_PLAN_DISCOUNT = 0.28


@dataclass(frozen=True)
class SyntheticConfig:
    seed: int = 2024
    start: dt.date = dt.date(2024, 10, 1)
    days: int = 730
    teams: int = 6
    # Median daily spend of one production account at the start, in USD (assumption).
    base_daily_usd: float = 900.0
    annual_growth: float = 0.22
    negotiated_discount: float = 0.06  # enterprise discount from list to contracted price
    plan_coverage: float = 0.85  # share of expected compute the savings plan is sized for
    anomalies: int = 18
    migrations: int = 3

    def __post_init__(self) -> None:
        if self.days < 60:
            raise ValueError("days must be at least 60 to cover two billing periods")
        if not 1 <= self.teams <= len(TEAMS):
            raise ValueError(f"teams must be between 1 and {len(TEAMS)}")
        if not 0 <= self.plan_coverage <= 1:
            raise ValueError("plan_coverage must be between 0 and 1")


@dataclass
class SyntheticBilling:
    charges: pa.Table  # FOCUS rows
    anomalies: pa.Table  # ground truth: account, service, first and last day, factor


def _month_start(d: dt.date) -> dt.date:
    return d.replace(day=1)


def _next_month(d: dt.date) -> dt.date:
    return (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


def generate(cfg: SyntheticConfig | None = None) -> SyntheticBilling:
    """Build the synthetic history for ``cfg``. Identical config gives identical output."""
    cfg = cfg or SyntheticConfig()
    rng = np.random.default_rng(cfg.seed)
    days = np.arange(cfg.days)
    dates = [cfg.start + dt.timedelta(days=int(d)) for d in days]
    weekday = np.array([d.weekday() for d in dates])
    trend = (1 + cfg.annual_growth) ** (days / 365.0)

    accounts = [
        (f"{100000000000 + 7919 * i + 17 * j:012d}", f"{team}-{env}", env)
        for i, team in enumerate(TEAMS[: cfg.teams])
        for j, env in enumerate(ENVIRONMENTS)
    ]
    env_scale = {"prod": 1.0, "staging": 0.25, "dev": 0.15}
    weights = np.array([c[4] for c in CATALOG])

    # Daily usage cost at list price for every (account, service, region) series.
    series: list[tuple[int, int, str, np.ndarray]] = []
    for a, (_, _, env) in enumerate(accounts):
        level = cfg.base_daily_usd * env_scale[env] * rng.lognormal(0, 0.45)
        chosen = rng.choice(
            len(CATALOG), size=rng.integers(5, 10), replace=False, p=weights / weights.sum()
        )
        mix = rng.dirichlet(weights[chosen] * 20)
        week = np.where(weekday >= 5, 0.55 if env != "prod" else 0.9, 1.0)
        for s, share in zip(chosen, mix, strict=True):
            region = str(rng.choice(CATALOG[s][3]))
            noise = rng.lognormal(0, 0.07, size=cfg.days)
            series.append((a, int(s), region, level * share * trend * week * noise))

    # Migrations: from a day on, part of one series' spend moves to another in the account.
    for _ in range(cfg.migrations):
        a = int(rng.integers(len(accounts)))
        own = [i for i, entry in enumerate(series) if entry[0] == a]
        if len(own) < 2:
            continue
        src, dst = rng.choice(own, size=2, replace=False)
        day = int(rng.integers(cfg.days // 4, 3 * cfg.days // 4))
        moved = series[src][3][day:] * 0.6
        series[src][3][day:] -= moved
        series[dst][3][day:] += moved * 0.85  # the move also saves some money

    # Anomalies: a series spikes for one to four days. Recorded as ground truth.
    truth: list[tuple[str, str, str, dt.date, dt.date, float]] = []
    for _ in range(cfg.anomalies):
        i = int(rng.integers(len(series)))
        length = int(rng.integers(1, 5))
        first = int(rng.integers(30, cfg.days - length))
        factor = float(rng.uniform(2.5, 8.0))
        series[i][3][first : first + length] *= factor
        acc, s, region, _ = series[i]
        truth.append(
            (
                accounts[acc][0],
                CATALOG[s][2],
                region,
                dates[first],
                dates[first + length - 1],
                round(factor, 2),
            )
        )

    # Savings plan: sized once a month on the previous month's expected compute.
    compute = [
        i
        for i, (_, s, _, _) in enumerate(series)
        if CATALOG[s][0] == "AWS" and CATALOG[s][1] == "Compute"
    ]
    expected_compute = (
        np.sum([series[i][3] for i in compute], axis=0) if compute else np.zeros(cfg.days)
    )
    plan_hourly = np.zeros(cfg.days)
    month_starts: list[int] = [0]
    for d in range(1, cfg.days):
        if dates[d].day == 1:
            month_starts.append(d)
    for k, m in enumerate(month_starts):
        end = month_starts[k + 1] if k + 1 < len(month_starts) else cfg.days
        basis = (
            expected_compute[max(0, m - 28) : max(1, m)].mean()
            if m
            else expected_compute[:7].mean()
        )
        plan_hourly[m:end] = cfg.plan_coverage * basis * (1 - SAVINGS_PLAN_DISCOUNT) / 24

    rows: dict[str, list[object]] = {name: [] for name in _COLUMNS}

    def add(**values: object) -> None:
        for name in _COLUMNS:
            rows[name].append(values.get(name))

    payer = "100000000000"
    for d, date in enumerate(dates):
        period_start = _month_start(date)
        period_end = _next_month(date)
        start_ts = dt.datetime.combine(date, dt.time())
        end_ts = start_ts + dt.timedelta(days=1)
        common = {
            "BillingAccountId": payer,
            "BillingAccountName": "Example Corp (synthetic)",
            "BillingCurrency": "USD",
            "BillingPeriodStart": dt.datetime.combine(period_start, dt.time()),
            "BillingPeriodEnd": dt.datetime.combine(period_end, dt.time()),
            "ChargePeriodStart": start_ts,
            "ChargePeriodEnd": end_ts,
            "x_Synthetic": True,
        }
        plan_daily = plan_hourly[d] * 24  # commitment available today, at discounted price
        compute_list = sum(series[i][3][d] for i in compute)
        covered_list = min(compute_list, plan_daily / (1 - SAVINGS_PLAN_DISCOUNT))
        coverage = covered_list / compute_list if compute_list else 0.0
        for i, (acc, s, region, cost) in enumerate(series):
            provider, category, service, _, _ = CATALOG[s]
            list_cost = float(cost[d])
            contracted = list_cost * (1 - cfg.negotiated_discount)
            account_id, account_name, _ = accounts[acc]
            base = {
                **common,
                "ChargeCategory": "Usage",
                "ChargeFrequency": "Usage-Based",
                "ProviderName": provider,
                "PublisherName": provider,
                "InvoiceIssuerName": provider,
                "RegionId": region,
                "ServiceCategory": category,
                "ServiceName": service,
                "SubAccountId": account_id,
                "SubAccountName": account_name,
                "SkuId": f"{service[:12].upper().replace(' ', '')}-{region}",
            }
            if i in compute and coverage > 0:
                committed = list_cost * coverage
                add(
                    **base,
                    ListCost=committed,
                    ContractedCost=committed * (1 - cfg.negotiated_discount),
                    BilledCost=0.0,
                    EffectiveCost=committed * (1 - SAVINGS_PLAN_DISCOUNT),
                    CommitmentDiscountId="sp-compute-1",
                    CommitmentDiscountStatus="Used",
                )
                list_cost -= committed
                contracted = list_cost * (1 - cfg.negotiated_discount)
            add(
                **base,
                ListCost=list_cost,
                ContractedCost=contracted,
                BilledCost=contracted,
                EffectiveCost=contracted,
            )
        if plan_daily > 0:
            unused = plan_daily - covered_list * (1 - SAVINGS_PLAN_DISCOUNT)
            if unused > 1e-6:
                add(
                    **common,
                    ChargeCategory="Usage",
                    ChargeFrequency="Usage-Based",
                    ProviderName="AWS",
                    PublisherName="AWS",
                    InvoiceIssuerName="AWS",
                    ServiceCategory="Compute",
                    ServiceName="Savings Plans for AWS Compute usage",
                    SubAccountId=payer,
                    SubAccountName="payer",
                    ListCost=0.0,
                    ContractedCost=0.0,
                    BilledCost=0.0,
                    EffectiveCost=unused,
                    CommitmentDiscountId="sp-compute-1",
                    CommitmentDiscountStatus="Unused",
                )
        if date.day == 1 or d == 0:
            month_days = (period_end - period_start).days
            fee = float(plan_hourly[d] * 24 * month_days)
            if fee > 0:
                add(
                    **{
                        **common,
                        "ChargePeriodStart": dt.datetime.combine(period_start, dt.time()),
                        "ChargePeriodEnd": dt.datetime.combine(period_end, dt.time()),
                    },
                    ChargeCategory="Purchase",
                    ChargeFrequency="Recurring",
                    ProviderName="AWS",
                    PublisherName="AWS",
                    InvoiceIssuerName="AWS",
                    ServiceCategory="Compute",
                    ServiceName="Savings Plans for AWS Compute usage",
                    SubAccountId=payer,
                    SubAccountName="payer",
                    ListCost=fee,
                    ContractedCost=fee,
                    BilledCost=fee,
                    EffectiveCost=0.0,  # amortized into the Used and Unused rows
                    CommitmentDiscountId="sp-compute-1",
                )

    charges = pa.table(
        {name: pa.array(values, type=_COLUMNS[name]) for name, values in rows.items()}
    )
    anomalies = pa.table(
        {
            "SubAccountId": [t[0] for t in truth],
            "ServiceName": [t[1] for t in truth],
            "RegionId": [t[2] for t in truth],
            "first_day": pa.array([t[3] for t in truth], type=pa.date32()),
            "last_day": pa.array([t[4] for t in truth], type=pa.date32()),
            "factor": [t[5] for t in truth],
        }
    )
    return SyntheticBilling(charges, anomalies)


_TS = pa.timestamp("s", tz="UTC")
_COLUMNS: dict[str, pa.DataType] = {
    "BilledCost": pa.float64(),
    "EffectiveCost": pa.float64(),
    "ListCost": pa.float64(),
    "ContractedCost": pa.float64(),
    "ConsumedQuantity": pa.float64(),
    "PricingQuantity": pa.float64(),
    "BillingAccountId": pa.string(),
    "BillingAccountName": pa.string(),
    "BillingCurrency": pa.string(),
    "BillingPeriodStart": _TS,
    "BillingPeriodEnd": _TS,
    "ChargePeriodStart": _TS,
    "ChargePeriodEnd": _TS,
    "ChargeCategory": pa.string(),
    "ChargeClass": pa.string(),
    "ChargeFrequency": pa.string(),
    "CommitmentDiscountId": pa.string(),
    "CommitmentDiscountStatus": pa.string(),
    "ProviderName": pa.string(),
    "PublisherName": pa.string(),
    "InvoiceIssuerName": pa.string(),
    "RegionId": pa.string(),
    "ServiceCategory": pa.string(),
    "ServiceName": pa.string(),
    "SkuId": pa.string(),
    "SubAccountId": pa.string(),
    "SubAccountName": pa.string(),
    "ResourceId": pa.string(),
    "x_Synthetic": pa.bool_(),
}
