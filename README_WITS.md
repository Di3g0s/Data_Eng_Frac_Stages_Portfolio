# WITS-style replay: practical runbook

This runbook complements the main [portfolio README](README.md) and the [architecture notes](docs/ARCHITECTURE.md). The wire format is a deliberately restricted **project-defined WITS Level 0-style** training contract, not a universal device specification.

## 1. Install and test (repository root)

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s WITS_starter -p 'test_*.py' -v
```

`databricks-sdk` is required by `upload_loop.py`. `pandas` and `openpyxl` are required by the workbook adapter. The network receiver, sender and receipt journal use the Python standard library. The Databricks CLI is a **separate** optional install.

## Existing data files are retained

The single-repository upgrade does not touch the existing `data/prepared/canonical.csv`, the canonical header, or either Stage 1/Stage 2 Excel workbook. All remain under their original paths in the same Git repository. When preparing a new dataset, write a separate stage-specific output file. See [data asset preservation](docs/DATA_ASSETS.md).

## 2. Prepare one original workbook

The bundled adapter assumes a particular workbook layout: rows 1–5 are metadata/header content; data begin on physical Excel row 6; date, time, pressure, slurry rate and clean rate are in columns 1, 2, 3, 5 and 7 respectively. Check these assumptions and the source time zone **before** using any figures for engineering analysis. The adapter currently assumes source timestamps are already UTC; it does not independently establish the original time zone.

```bash
cd WITS_starter
python data/raw_2_prepared.py \
  --raw-file 'data/raw/16B(78)-32_Stage 1_Treatment Data.xlsx' \
  --output data/prepared/stage1.csv
```

When more than one source workbook is in `data/raw`, select one with `--raw-file`. Stage ID is inferred from the `Stage N` filename. The adapter intentionally refuses to mix multiple originals into one CSV because `replay.py --original` hashes **one original** for record-level provenance. Do not paste Stage 2 rows into a Stage 1 replay. **Migration note:** the former adapter added five extra rows to the recorded physical Excel row number; re-prepared files therefore produce different stable source IDs. Use a new run ID and reconcile against fresh manifests rather than mixing old and corrected IDs.

Preview a frame and create a source-identity manifest:

```bash
python replay.py --csv data/prepared/stage1.csv \
  --original 'data/raw/16B(78)-32_Stage 1_Treatment Data.xlsx' \
  --max-rows 30 --manifest data/prepared/expected_demo01.jsonl --check-only
```

## 3. Run collector and sender

From `WITS_starter`, use **terminal A**:

```bash
python collector.py serve --db spool/receipts.sqlite --port 9000 --run-id demo01
```

Use **terminal B**, also from `WITS_starter`:

```bash
python replay.py --csv data/prepared/stage1.csv \
  --original 'data/raw/16B(78)-32_Stage 1_Treatment Data.xlsx' \
  --max-rows 30 --speed 0
```

The receiver listens on `127.0.0.1:9000` and is not protected for public exposure. `--speed 10` means 10 historical seconds per wall-clock second; `--speed 0` sends without replay delays. TCP `sendall` does **not** guarantee durable receipt.

## 4. Export and inspect actual receipts

```bash
python collector.py inspect --db spool/receipts.sqlite
python collector.py export --db spool/receipts.sqlite --out spool/ready --batch-rows 500
python inspect_received.py
```

SQLite persists every received frame including errors; the exporter produces only completed `.jsonl` files. Export batches contain up to 500 receipts, **not** five event-time minutes. Keep the journal after upload. Do not silently overwrite a completed batch when its bytes differ.

## 5. Optional Databricks upload

Create the destination schema/volume in Databricks, and grant the selected identity permission to access it. For example:

```sql
CREATE SCHEMA IF NOT EXISTS main.frac_demo;
CREATE VOLUME IF NOT EXISTS main.frac_demo.landing;
```

For an existing Databricks CLI/SDK auth profile named `frac-demo`:

```bash
python upload_loop.py --once --profile frac-demo
python upload_loop.py --profile frac-demo --interval 30
```

For unattended uploads, configure `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET` through Codespaces Secrets and omit `--profile`; the SDK uses OAuth M2M. You can override the landing destination with `--destination` or `WITS_DESTINATION`. Do **not** put tokens in source code or committed files.

`01_ingest_bronze.py` is a Databricks notebook source file. Import it into your workspace, set the correct catalog/schema/volume, and run it on compatible Databricks compute. **It has not been validated against this project's workspace.**

## 6. Reconciliation and limitations

Compare the expected manifest's `source_sample_id` and `expected_raw_sha256` to the exported receipts' `fields["9908"]` and `raw_sha256`. A count match alone can hide missing IDs or duplicates. Re-sending the same source is permitted; Bronze stores receipts, while Silver deduplication remains future work. For additional constraints and security boundaries, see [architecture notes](docs/ARCHITECTURE.md).
