# Roadmap — build credible evidence, not generic claims

## Completed in the codebase

- [x] Local historical sender and TCP frame decoder
- [x] Persistent receipt journal, parse-error capture and repeatable JSONL exports
- [x] Polling Databricks SDK uploader with read-back hash verification
- [x] Synthetic sender/collector/journal tests
- [x] Databricks Auto Loader Bronze notebook **template**

## Next steps, in priority order

1. **Validate a real measurement source**: cite the publisher/license, inspect workbook headers and units, confirm timestamp time zone, and record per-stage source hashes. Do not mix two original workbooks under one source hash.
2. **Prove Databricks ingestion**: show the JSONL landing path, an actual Auto Loader job run, checkpoint behavior and ingested Bronze row count after first and repeated uploads.
3. **Implement Silver**: parse record-99 fields, normalize numeric units, reject invalid times/identifiers, quarantine malformed rows, deduplicate with `source_sample_id` plus source hash/mapping version; test late-arriving and repeated receipts.
4. **Implement Gold**: compute domain-relevant stage metrics, e.g., stage duration, pressure distribution, fluid volume from a validated rate channel; expose sample SQL queries or a dashboard.
5. **Deployment and reliability**: service-principal OAuth, non-Codespace runner, health metrics, alerting, idempotent reconciliation, automated Databricks Jobs, and data-quality checks.
6. **Portfolio evidence**: screenshots of a successful pipeline/job run (redact workspace/credentials), sample reconciliation report, and a short architecture/demo video.

### Honest resume description (current state)

> Built a Python WITS-style TCP replay and ingestion prototype for frac-treatment measurements with SQLite receipt journaling, repeatable JSONL export, Databricks SDK upload verification and a Databricks Bronze Auto Loader template. Added synthetic end-to-end tests and explicit data provenance. Further lakehouse validation and Silver/Gold models are planned.
