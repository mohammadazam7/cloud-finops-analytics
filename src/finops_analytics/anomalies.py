"""Daily cost anomalies per account, service and region, scored against planted ones.

A day is anomalous when its cost is far above what the same series usually costs:

    baseline = median of the previous ``window`` days (the day itself excluded)
    spread   = 1.4826 * median absolute deviation over the same days
    score    = (cost - baseline) / max(spread, floor * baseline, 0.01)

and the day is flagged when ``score >= threshold`` and the excess is at least
``min_excess`` in currency, so cent-level noise on tiny series is ignored. The median
and MAD are robust: a few spike days inside the window barely move them, which a mean
and standard deviation would not survive. Consecutive flagged days in one series are
one incident.

The synthetic history plants anomalies and records them as ground truth, so detection
can be measured: an incident is a true positive when it overlaps a planted anomaly on
the same account, service and region.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

Key = tuple[str, str, str]  # account, service, region

MAD_TO_SIGMA = 1.4826


@dataclass(frozen=True)
class Settings:
    window: int = 28
    threshold: float = 6.0
    floor: float = 0.05
    min_excess: float = 1.0


@dataclass(frozen=True)
class Incident:
    key: Key
    first_day: dt.date
    last_day: dt.date
    excess: float  # cost above baseline, summed over the incident's days
    peak_score: float


@dataclass(frozen=True)
class Scored:
    incidents: int
    planted: int
    true_positives: int  # incidents that overlap a planted anomaly
    found: int  # planted anomalies overlapped by at least one incident

    @property
    def precision(self) -> float:
        return self.true_positives / self.incidents if self.incidents else 0.0

    @property
    def recall(self) -> float:
        return self.found / self.planted if self.planted else 0.0


def flag(costs: Sequence[float] | np.ndarray, settings: Settings | None = None) -> np.ndarray:
    """Per-day anomaly scores; days without a full window score 0."""
    s = settings or Settings()
    x = np.asarray(costs, dtype=np.float64)
    scores = np.zeros(len(x))
    for t in range(s.window, len(x)):
        past = x[t - s.window : t]
        baseline = float(np.median(past))
        spread = MAD_TO_SIGMA * float(np.median(np.abs(past - baseline)))
        excess = x[t] - baseline
        if excess < s.min_excess:
            continue
        scores[t] = excess / max(spread, s.floor * baseline, 0.01)
    return scores


def incidents(
    key: Key,
    days: Sequence[dt.date],
    costs: Sequence[float] | np.ndarray,
    settings: Settings | None = None,
) -> list[Incident]:
    """Group consecutive flagged days of one series into incidents."""
    s = settings or Settings()
    x = np.asarray(costs, dtype=np.float64)
    scores = flag(x, s)
    found: list[Incident] = []
    start: int | None = None
    for t in range(len(x) + 1):
        hot = t < len(x) and scores[t] >= s.threshold
        if hot and start is None:
            start = t
        elif not hot and start is not None:
            excess = 0.0
            for d in range(start, t):
                baseline = float(np.median(x[d - s.window : d]))
                excess += x[d] - baseline
            found.append(
                Incident(
                    key, days[start], days[t - 1], round(excess, 2), float(scores[start:t].max())
                )
            )
            start = None
    return found


def daily_series(charges: pa.Table) -> tuple[list[dt.date], dict[Key, np.ndarray]]:
    """Daily effective cost of usage charges per account, service and region.

    Purchases (commitment fees) are left out: they are scheduled, not anomalies. So is
    the unused part of a commitment, which is spiky by nature (it rises whenever usage
    dips, every weekend) and is measured by commitment utilization instead.
    """
    usage = pc.equal(charges["ChargeCategory"], "Usage")
    unused = pc.fill_null(pc.equal(charges["CommitmentDiscountStatus"], "Unused"), False)
    rows = charges.filter(pc.and_(usage, pc.invert(unused))).select(
        ["SubAccountId", "ServiceName", "RegionId", "ChargePeriodStart", "EffectiveCost"]
    )
    data = rows.to_pydict()
    starts = [_day(v) for v in data["ChargePeriodStart"]]
    first, last = min(starts), max(starts)
    days = [first + dt.timedelta(days=i) for i in range((last - first).days + 1)]
    index = {d: i for i, d in enumerate(days)}
    series: dict[Key, np.ndarray] = defaultdict(lambda: np.zeros(len(days)))
    for account, service, region, day, cost in zip(
        data["SubAccountId"],
        data["ServiceName"],
        data["RegionId"],
        starts,
        data["EffectiveCost"],
        strict=True,
    ):
        series[(account, service, region or "")][index[day]] += cost or 0.0
    return days, dict(series)


def _day(value: object) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    raise TypeError(f"ChargePeriodStart holds {value!r}, not a date")


def detect(charges: pa.Table, settings: Settings | None = None) -> list[Incident]:
    days, series = daily_series(charges)
    out: list[Incident] = []
    for key in sorted(series):
        out += incidents(key, days, series[key], settings)
    return out


def score(found: Iterable[Incident], planted: pa.Table) -> Scored:
    """Compare incidents with the planted anomalies of the synthetic history."""
    truth = [
        ((r["SubAccountId"], r["ServiceName"], r["RegionId"]), r["first_day"], r["last_day"])
        for r in planted.to_pylist()
    ]
    found = list(found)

    def overlaps(i: Incident, t: tuple[Key, dt.date, dt.date]) -> bool:
        return i.key == t[0] and i.first_day <= t[2] and t[1] <= i.last_day

    true_positives = sum(any(overlaps(i, t) for t in truth) for i in found)
    hit = sum(any(overlaps(i, t) for i in found) for t in truth)
    return Scored(len(found), len(truth), true_positives, hit)
