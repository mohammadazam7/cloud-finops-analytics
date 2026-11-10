# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- dbt project on DuckDB and BigQuery targets: typed staging over the FOCUS sample and the
  synthetic history, keyed intermediate charges, service, region, account and date
  dimensions, an incremental `fct_cost_daily` with an enforced contract and a restatement
  window, `fct_commitment_utilization` and `agg_commitment_daily`, with reconciliation
  and bounds tests.
- Governed metric layer: seven cost metrics in `metrics/metrics.yml`, compiled to SQL at
  any grain (`finops metric`), and a generated metric dictionary (`finops metrics`).
- Architecture notes and ADRs on rollups from additive parts and the incremental
  lookback.

## [0.1.0] - 2026-11-04

### Added
- FOCUS 1.0 conformance checks with repairable and error findings, and normalisation of
  unambiguous repairs (`finops check`).
- Download of the FinOps Foundation FOCUS sample pinned to a commit and checksum.
- Seeded synthetic 24-month billing history in FOCUS columns, labelled `x_Synthetic`,
  with an anomaly ground-truth table (`finops synthesize`).
- Parquet raw zone with a manifest of row counts, checksums and provenance
  (`finops load-sample`, `finops verify`).
- CONTRIBUTING, SECURITY, CODEOWNERS, pre-commit hooks, a lock file and a dependency
  audit in CI.
- Project foundation: package layout, CI (ruff, mypy in strict mode, pytest on Python
  3.11 to 3.13), roadmap, issue and pull request templates.

[Unreleased]: https://github.com/mohammadazam7/cloud-finops-analytics/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mohammadazam7/cloud-finops-analytics/releases/tag/v0.1.0
