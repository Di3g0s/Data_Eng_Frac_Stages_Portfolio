# Architecture and engineering decisions

## Design scope

This repository demonstrates a **historical replay** of hydraulic-fracturing treatment measurements, not telemetry from a live wellsite or a production-certified WITS implementation. `WITS_starter/wits.py` implements a deliberately restricted, project-defined record-99 profile. The TCP collector listens only on `127.0.0.1` without TLS or client authentication; do not expose it to external hosts.

## End-to-end data lineage

1. `data/raw_2_prepared.py` reads one original workbook and creates a canonical CSV. Source row numbers refer to physical Excel rows. **The workbook layout and source timestamp time zone must be verified for every source.**
2. `replay.py` hashes the selected original workbook and creates a stable `source_sample_id` from the source hash, worksheet, physical row, well, and stage. It retains source **event time** and sends synthetic WITS-style frames via loopback TCP.
3. `collector.py` uses `FrameDecoder` to recognize frame boundaries across arbitrary TCP chunks. It journals completed and malformed/truncated frames.
4. `journal.py` persists receipts and byte-for-byte raw frames in SQLite, assigns durable export ranges, and atomically publishes completed JSONL batches. An export rerun checks file content rather than silently overwriting.
5. `upload_loop.py` polls completed batches (default 30 seconds), uploads to a Unity Catalog Volume using the Python SDK and checks remote SHA-256. It does not delete local receipts after uploading.
6. `01_ingest_bronze.py` is an **unverified Databricks notebook template** that uses Auto Loader with a stable checkpoint to append the raw receipt envelope to Bronze Delta.

## Reliability boundaries

| Boundary | Implemented guarantee | Not guaranteed |
| --- | --- | --- |
| TCP sender → collector | Retried sends; source identity stable across replays | Exactly-once delivery; durable ACK from collector |
| Collector → SQLite | Receipts committed on local disk | Survival of destroyed/lost Codespace or unreceived socket tail |
| SQLite → JSONL | Deterministic export ranges and atomic completed-file publication | Exactly five event-time minutes per batch |
| JSONL → Databricks Volume | No overwrite; remote byte-hash verification; retries | Guaranteed 24/7 execution; transactional cross-system commit |
| Auto Loader → Bronze | Template checkpointing and raw-envelope preservation | Verified workspace deployment or downstream deduplication |

## Engineering data contract

Canonical CSV fields: `well_id`, `stage_id`, `event_time_utc`, `pressure_psi`, `clean_rate_bpm`, `slurry_rate_bpm`, `source_sheet`, and `source_row`.

Units are **declared targets**, not a validation of the source workbook: pressure is psi, fluid rates are US bbl/min, and event times are UTC. A source mapping audit is required before interpreting totals. Missing pressure/rates remain absent rather than silently becoming zero. The WITS parser preserves strings; typed casts belong downstream.

## Security and provenance

Use the SDK profile or OAuth service-principal secrets stored outside Git. Never commit `.databrickscfg`, personal tokens or service-principal secrets. The included historical workbook files need an explicit source citation and redistribution-rights check before public reuse; removing them in a later commit would not erase earlier Git history. The tests generate synthetic fixtures and make no claims about frac-event detection accuracy.
