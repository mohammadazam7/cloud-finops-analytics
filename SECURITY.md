# Security policy

## Reporting a problem

Please report security issues privately through GitHub's
[security advisories](https://github.com/mohammadazam7/cloud-finops-analytics/security/advisories/new)
rather than in a public issue. Expect an acknowledgement within a few days.

## Data and credentials

- The billing data used here is the public FOCUS sample data (CC BY 4.0), pinned to a
  commit and checked against a SHA-256 checksum on download. No real billing export is
  stored in the repository.
- Billing exports reveal account structure and spend. Real exports belong in a
  location outside the repository; `data/` is ignored by git.
- Credentials (for example a BigQuery service account key) are read from the
  environment and are never committed.
