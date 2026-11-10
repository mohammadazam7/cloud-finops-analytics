# Roadmap

Each milestone lands on its own branch with tests and is merged when complete. Checked
items are done.

- [x] **M1: Foundation and billing data** (Nov 2 to Nov 5). Package layout, CI, a
      download script for the FOCUS sample data, ingestion with conformance checks
      against the FOCUS specification, and a seeded synthetic multi-account history
      that follows the same schema.
- [x] **M2: Cost models and metrics** (Nov 6 to Nov 10). dbt project on DuckDB and
      BigQuery targets: staging, intermediate and mart layers; incremental daily cost
      fact with partitioning and clustering; tests and contracts; governed cost metrics
      reconciled to invoice totals.
- [ ] **M3: Forecasting and anomalies** (Nov 11 to Nov 19). Per-service spend
      forecasting with rolling-origin backtests and prediction intervals; anomaly
      detection with attribution to service, account, region and SKU.
- [ ] **M4: Commitments and accounts** (Nov 20 to Nov 27). Commitment planning as an
      optimisation over the usage distribution, with expected savings and risk;
      account health, expansion and churn-risk scoring; cohort analysis.
- [ ] **M5: Reporting and Spend Atlas** (Nov 28 to Dec 6). LookML model validated in
      CI, an automated monthly business review, and an interactive 3D web app.
- [ ] **M6: v1.0** (Dec 7 to Dec 11). Problem statement, quarterly roadmap, executive
      readout with recommendations, architecture notes, decision records and release.
