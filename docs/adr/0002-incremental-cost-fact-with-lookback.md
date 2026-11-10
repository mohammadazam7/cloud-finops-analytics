# 0002. Load the cost fact incrementally with a lookback window

**Status:** Accepted

## Context

Billing exports are restated. Providers revise the last few days of charges as usage
records arrive late and credits are applied, so appending only new dates would freeze
early, wrong numbers. Rebuilding two years of history on every run is the safe
alternative, but on BigQuery it scans the full table each time.

## Decision

`fct_cost_daily` is incremental. Each run recomputes every date from the latest loaded
date minus `cost_lookback_days` (3 by default) and replaces those rows by their grain
key, using `delete+insert` on DuckDB and `merge` on BigQuery. On BigQuery the table is
partitioned by charge date, so the reload touches only those partitions.

## Consequences

- Restated amounts inside the window are picked up automatically. Older restatements,
  and a grain row that disappears from a restated day, need `dbt build --full-refresh`,
  which is also the documented recovery path.
- Runs are idempotent: running twice loads the same rows once.
- The window is a variable, so a provider with slower restatements can widen it
  without a code change.
