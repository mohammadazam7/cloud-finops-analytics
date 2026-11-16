# Forecasting daily spend

Status: baselines and the backtest are in place; richer models come next and have to beat
the numbers below on the same folds to be kept.

## Method

- **Rolling origin.** The series is cut at an origin, a forecaster sees only the days
  before it and predicts the next 28, then the origin moves forward a week. The first
  origin comes after 365 days so every forecaster has a full year behind it.
- **WAPE** (total absolute error over total actual spend) is the headline error. A mean
  of daily percentage errors would let small days dominate.
- **Bias** is total error over total spend; negative means the forecast ran high.
- **Prediction intervals** are the empirical quantiles of backtest errors at each step
  ahead. Their coverage is measured on the later half of the folds, which the interval
  never saw, so it is an out-of-sample number.

## Baselines

| Model | What it predicts |
|---|---|
| `naive_last` | Every future day equals the last observed day |
| `seasonal_naive` | Each day equals the same weekday of the last week |
| `seasonal_drift` | Last week's shape, moved by the average week-over-week change of the last eight weeks |

## Results on the synthetic history

All services together, 730 days of **synthetic** spend (seed 7), 49 folds, 28 days ahead.
Reproduce with `finops forecast --warehouse data/warehouse.duckdb`.

| Model | WAPE | Bias | Coverage of the 80% interval |
|---|---|---|---|
| `seasonal_drift` | 2.0% | -0.0% | 74.7% |
| `seasonal_naive` | 2.1% | +0.9% | 73.7% |
| `naive_last` | 8.4% | -6.1% | 70.6% |

What this says:

- The weekly pattern is most of the signal. Ignoring it costs four times the error.
- Adding the recent trend removes the bias (`seasonal_naive` runs about 1% low on a
  growing bill) but barely moves WAPE.
- The 80% intervals cover about 75%. They are sized on 24 folds, which is few, and the
  planted cost spikes fall unevenly between the two halves. The intervals are too narrow
  as they stand and should not be presented as 80% until this is fixed.

These numbers describe generated data with a known weekly cycle and growth rate, so they
show the method works, not how well real bills can be forecast.
