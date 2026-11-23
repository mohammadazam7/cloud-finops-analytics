import datetime as dt

import numpy as np
import pyarrow as pa
import pytest

from finops_analytics.anomalies import Incident, Settings, detect, flag, incidents, score
from finops_analytics.synthetic import generate

KEY = ("acct", "Compute", "us-east-1")
START = dt.date(2025, 1, 1)


def _days(n: int) -> list[dt.date]:
    return [START + dt.timedelta(days=i) for i in range(n)]


def _series(n: int = 90, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    weekly = 1 + 0.2 * np.sin(np.arange(n) * 2 * np.pi / 7)
    return 100 * weekly * rng.normal(1.0, 0.03, n)


def test_a_quiet_series_has_no_incidents() -> None:
    assert incidents(KEY, _days(90), _series()) == []


def test_a_spike_is_one_incident_with_its_excess() -> None:
    x = _series()
    x[50:53] *= 4
    [found] = incidents(KEY, _days(90), x)
    assert (found.first_day, found.last_day) == (START + dt.timedelta(50), START + dt.timedelta(52))
    assert found.excess == pytest.approx(3 * float(np.median(x[22:50])) * 3, rel=0.25)
    assert found.peak_score >= 6


def test_days_without_a_full_window_are_never_flagged() -> None:
    x = _series()
    x[10] *= 10
    assert flag(x)[:28].tolist() == [0.0] * 28
    assert incidents(KEY, _days(90), x) == []


def test_tiny_excesses_are_ignored_however_unusual() -> None:
    x = np.full(60, 0.10)
    x[40] = 0.90  # nine times the usual cost, but 80 cents
    assert incidents(KEY, _days(60), x) == []
    assert incidents(KEY, _days(60), x, Settings(min_excess=0.5)) != []


def test_the_baseline_is_not_dragged_up_by_an_earlier_spike() -> None:
    x = _series()
    x[40:44] *= 5
    x[60] *= 3
    found = incidents(KEY, _days(90), x)
    assert [i.first_day for i in found] == [START + dt.timedelta(40), START + dt.timedelta(60)]


def test_scoring_matches_on_key_and_overlapping_days() -> None:
    planted = pa.table(
        {
            "SubAccountId": ["acct", "acct"],
            "ServiceName": ["Compute", "Storage"],
            "RegionId": ["us-east-1", "us-east-1"],
            "first_day": [dt.date(2025, 2, 1), dt.date(2025, 3, 1)],
            "last_day": [dt.date(2025, 2, 3), dt.date(2025, 3, 1)],
        }
    )
    found = [
        Incident(KEY, dt.date(2025, 2, 3), dt.date(2025, 2, 4), 10.0, 9.0),
        Incident(KEY, dt.date(2025, 3, 1), dt.date(2025, 3, 1), 10.0, 9.0),  # wrong service
    ]
    result = score(found, planted)
    assert (result.incidents, result.true_positives, result.found) == (2, 1, 1)
    assert (result.precision, result.recall) == (0.5, 0.5)


def test_on_the_synthetic_history_most_planted_anomalies_are_found() -> None:
    billing = generate()
    result = score(detect(billing.charges), billing.anomalies)
    # Measured with the default settings; see the README for what the misses are.
    assert (result.planted, result.found) == (18, 17)
    assert (result.incidents, result.true_positives) == (21, 17)
