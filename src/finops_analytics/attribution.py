"""Why did spend move? Split a change in cost between the things that could have caused it.

Detection says that a series cost more than usual. Attribution answers the question a
person asks next, usually about a total: spend was up 2,400 USD over these three days,
which services, accounts, regions or SKUs is that?

For a period and a dimension (or several together), each value gets:

    expected = for each day of the period, its mean cost on the same weekday in the
               ``window`` days before the period, summed over the period
    change   = what it actually cost in the period - expected
    share    = change / the total change

Two choices in that definition matter.

The mean is used, not the median the detector uses, because means add up. The expected
cost of the total is exactly the sum of the expected costs of its parts, so the changes
of the parts sum to the change of the total and every dollar of the movement is assigned
once. A median baseline is more robust and would leave a remainder nobody can explain.

The same weekday is used because spend has a weekly rhythm. Compared with a plain
average of the last four weeks, every Saturday looks like a fall in the largest service
and every Monday like a rise, and those ordinary swings bury the real cause. With
``seasonal=False`` the plain average is used; the tests show the difference on the
synthetic history.

The same usage rows are counted as in detection: purchases and the unused part of a
commitment are left out.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pyarrow as pa
import pyarrow.compute as pc

DIMENSIONS = {
    "account": "SubAccountId",
    "service": "ServiceName",
    "region": "RegionId",
    "sku": "SkuId",
    "category": "ServiceCategory",
    "provider": "ProviderName",
}


@dataclass(frozen=True)
class Driver:
    key: tuple[str, ...]  # one value per dimension asked for
    expected: float
    actual: float

    @property
    def change(self) -> float:
        return self.actual - self.expected


@dataclass(frozen=True)
class Explanation:
    by: tuple[str, ...]
    first_day: dt.date
    last_day: dt.date
    baseline_days: int  # days before the period the expectation was taken from
    expected: float
    actual: float
    drivers: tuple[Driver, ...]  # largest movement first, in either direction
    others: int  # values not listed in ``drivers``
    others_change: float  # their combined change, so the listed and the rest sum to the total

    @property
    def change(self) -> float:
        return self.actual - self.expected

    def share(self, driver: Driver) -> float | None:
        """The part of the total change this driver accounts for; above 1 or below 0 when
        other values moved the opposite way. None when the total did not move."""
        return driver.change / self.change if abs(self.change) > 1e-9 else None


def _column(dimension: str) -> str:
    try:
        return DIMENSIONS[dimension]
    except KeyError:
        known = ", ".join(sorted(DIMENSIONS))
        raise ValueError(f"unknown dimension {dimension!r}; choose from {known}") from None


def _day(value: object) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    raise TypeError(f"ChargePeriodStart holds {value!r}, not a date")


def explain(
    charges: pa.Table,
    first_day: dt.date,
    last_day: dt.date,
    *,
    by: Sequence[str] = ("service",),
    where: Mapping[str, str] | None = None,
    window: int = 28,
    top: int | None = 5,
    seasonal: bool = True,
) -> Explanation:
    """Attribute the change in cost over ``first_day`` to ``last_day`` (inclusive).

    ``by`` names one or more dimensions; several together attribute to their
    combinations, such as each account's use of each service. ``where`` restricts the
    question to one value of a dimension, for example one account. ``top`` limits how
    many drivers are listed; the rest are summed in ``others_change``. Drivers are
    ordered by the size of their change in either direction, so a large fall that hides
    a rise is listed next to it.
    """
    if not by:
        raise ValueError("name at least one dimension to attribute by")
    if last_day < first_day:
        raise ValueError("the period ends before it starts")
    if window < 1:
        raise ValueError("the baseline window must be at least one day")
    if top is not None and top < 1:
        raise ValueError("top must be at least 1, or None for every value")
    by_columns = [_column(d) for d in by]
    filters = {_column(d): value for d, value in (where or {}).items()}

    usage = pc.equal(charges["ChargeCategory"], "Usage")
    unused = pc.fill_null(pc.equal(charges["CommitmentDiscountStatus"], "Unused"), False)
    keep = pc.and_(usage, pc.invert(unused))
    for column, value in filters.items():
        keep = pc.and_(keep, pc.fill_null(pc.equal(charges[column], value), False))
    needed = list(dict.fromkeys([*by_columns, "ChargePeriodStart", "EffectiveCost"]))
    data = charges.filter(keep).select(needed).to_pydict()

    baseline_start = first_day - dt.timedelta(days=window)
    # Baseline cost per value and weekday, and what each value cost in the period.
    before: dict[tuple[str, ...], list[float]] = defaultdict(lambda: [0.0] * 7)
    during: dict[tuple[str, ...], float] = defaultdict(float)
    seen_days: set[dt.date] = set()
    for row in range(len(data["EffectiveCost"])):
        day = _day(data["ChargePeriodStart"][row])
        if not baseline_start <= day <= last_day:
            continue
        key = tuple(str(data[c][row]) if data[c][row] is not None else "" for c in by_columns)
        cost = data["EffectiveCost"][row] or 0.0
        if day < first_day:
            before[key][day.weekday()] += cost
            seen_days.add(day)
        else:
            during[key] += cost

    if not seen_days:
        raise ValueError(
            f"no usage in the {window} days before {first_day}, so there is nothing to compare with"
        )
    # Days with no rows at all are missing data, not zero spend; average over what exists.
    baseline_days = len(seen_days)
    per_weekday = [sum(d.weekday() == w for d in seen_days) for w in range(7)]
    period = [first_day + dt.timedelta(days=i) for i in range((last_day - first_day).days + 1)]

    def expected_for(costs: list[float]) -> float:
        total = 0.0
        for day in period:
            w = day.weekday()
            if seasonal and per_weekday[w]:
                total += costs[w] / per_weekday[w]
            else:  # no such weekday in the baseline: fall back to the plain daily mean
                total += sum(costs) / baseline_days
        return total

    found = [
        Driver(key, expected_for(before[key]) if key in before else 0.0, during.get(key, 0.0))
        for key in sorted(set(before) | set(during))
    ]
    expected = sum(d.expected for d in found)
    actual = sum(d.actual for d in found)
    found.sort(key=lambda d: (-abs(d.change), d.key))
    listed = found if top is None else found[:top]
    rest = found[len(listed) :]
    return Explanation(
        by=tuple(by),
        first_day=first_day,
        last_day=last_day,
        baseline_days=baseline_days,
        expected=expected,
        actual=actual,
        drivers=tuple(listed),
        others=len(rest),
        others_change=sum(d.change for d in rest),
    )


def format_explanation(result: Explanation) -> str:
    """A few lines a person can read: the total first, then who it was."""
    span = (
        f"{result.first_day}"
        if result.first_day == result.last_day
        else f"{result.first_day} to {result.last_day}"
    )
    lines = [
        f"{span}: {result.actual:,.2f} against {result.expected:,.2f} expected "
        f"({result.change:+,.2f}), by {' and '.join(result.by)}"
    ]
    for driver in result.drivers:
        share = result.share(driver)
        part = "" if share is None else f"  {share:6.1%} of the change"
        lines.append(f"  {' / '.join(driver.key):<44} {driver.change:+12,.2f}{part}")
    if result.others:
        lines.append(f"  {f'{result.others} others':<44} {result.others_change:+12,.2f}")
    return "\n".join(lines)
