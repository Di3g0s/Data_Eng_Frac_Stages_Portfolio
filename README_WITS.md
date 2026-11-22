# WITS starter: from zero to your first ingested treatment record

Start here for the practical exercise. Read Section 8 of `../Frac_Stage_Replay_7_Day_Plan.md` for the architecture, channel contract, Silver rules and limitations.

**Included:** a local TCP sender, stream decoder, collector, disk journal, repeatable JSON exporter, tests, and a Databricks Bronze notebook template. The sender consumes YOUR prepared real-data CSV. No Utah FORGE measurements are bundled. Test fixtures are synthetic and are never portfolio field results.

The local programs use the Python standard library. Use Python 3.10+ with `sqlite3` available. Commands below use `python3`; on Windows your command may be `python`. Run them from this `wits_starter` directory. You do not need Docker, Kafka, a paid WITS server, or serial hardware for this exercise.

## 1. Check your environment

```bash
python3 --version
python3 -m unittest -v test_wits.py
```

Ten tests should pass, including an actual loopback TCP run. They test transport mechanics and evidence preservation; they do not validate frac interpretations or your Databricks environment.

## 2. Prepare a small slice of REAL measurements

Download the source through the links in the main guide, extract the selected workbook, and keep its bytes unchanged. For these commands, put that workbook at `data/original.xlsx`. If your source is a CSV, use its real path instead of that name. Use one original file per sender invocation.

Create `data/canonical.csv` with this header (also in `canonical_header.csv`):

```csv
well_id,stage_id,event_time_utc,pressure_psi,clean_rate_bpm,slurry_rate_bpm,source_sheet,source_row
```

| Column | How to fill it |
|---|---|
| `well_id`, `stage_id` | Documented identities; stage may come from the worksheet. Text is accepted. |
| `event_time_utc` | Original measurement timestamp converted to UTC, e.g. the FORMAT `YYYY-MM-DDTHH:MM:SSZ`. Confirm the original zone first; do not replace it with today's time. |
| `pressure_psi` | Verified treating-pressure channel converted to psi. Blank if missing. |
| `clean_rate_bpm` | Verified clean-fluid rate in US bbl/min; leave blank if unavailable. |
| `slurry_rate_bpm` | Verified slurry rate in US bbl/min; leave blank if unavailable. Never put clean rate here simply to fill it. |
| `source_sheet` | Original worksheet name; use a documented label such as `csv` for a source CSV. |
| `source_row` | Original physical row number, captured BEFORE filtering or sorting. It must stay the same across replays. |

after create the .csv you may run the following to test it: 
python3 replay.py --csv data/prepared/canonical.csv --original data/raw/16B\(78\)-32_Stage\ 1_Treatment\ Data.xlsx --max-rows 10 --check-only

Do not guess column names or measurement basis. If rate basis cannot be resolved, stop the engineering calculations and investigate the source README. The starter carries both supported rate channels; concentration and alternative rate bases require an explicit extension.

In your Day 1 notebook, first attach the original row number to the loaded dataframe, then map columns, normalize time/units, select two stages, sort, and export without a dataframe index. For an Excel table read with a zero-based header row `header_row`, and no skipped/removed rows before numbering:

```python
raw = pd.read_excel(original_path, sheet_name=actual_sheet, header=header_row)
raw["source_row"] = range(header_row + 2, header_row + 2 + len(raw))
raw["source_sheet"] = actual_sheet
# Inspect actual headers; build canonical columns using the verified mapping.
# Perform filtering only AFTER capturing source_row.
# canonical.to_csv("data/canonical.csv", index=False, na_rep="")
```

This is an adaptation pattern, not a ready-made FORGE workbook parser. Date and time may need combining; `skiprows`, non-tabular headers and blank rows may require different row-number handling. Keep a mapping note with source names, units, timezone, exclusions and code revision. This training profile accepts printable ASCII channel values; if source sheet names need an ASCII alias, record the reversible alias in that note. Do not silently discard characters.

Check the first 300 rows and write a manifest of exactly what you intend to send:

```bash
python3 replay.py --csv data/canonical.csv --original data/original.xlsx --max-rows 300 --manifest data/expected_demo01.jsonl --check-only
```

You should see a source hash, row count and the first encoded frame built from your real data. Open it and verify the pressure/rate against the corresponding source row. The sample ID hashes original-file SHA-256, sheet, original row, well and stage; it stays stable on repeated delivery. The manifest records provenance and expected payload hashes. Keep it outside the WITS ingestion folder.

## 3. Start the collector in terminal A

```bash
python3 collector.py serve --db spool/receipts.sqlite --port 9000 --run-id demo01
```

Wait for `listening`. It accepts one connection at a time on `127.0.0.1`, so both programs run on the same computer. `9000` is our selected port, not a universal WITS port. Leave this terminal open.

## 4. Start the sender in terminal B

```bash
python3 replay.py --csv data/canonical.csv --original data/original.xlsx --max-rows 300 --speed 10
```

`--speed 10` means ten historical seconds per real second. It preserves uneven source intervals and gaps; it does not manufacture one-second samples. Use `--speed 0` for a fast functional run. The row limit is applied to the CSV before timestamp sorting; use the same selection as your manifest.

Terminal A should print `connected`, `journaled`, then `connection_closed`. The sender's `send_finished` confirms socket transmission, not durable receipt of every measurement. Connection failures trigger up to five attempts, repeating the selected input with the same sample IDs. After an uncertain shutdown, rerun and reconcile. Keep `demo01` for duplicate tests; change the run ID only for a separate experiment and filter the scorecard accordingly.

## 5. Inspect and export completed files

In terminal B, after the send completes:

```bash
python3 collector.py inspect --db spool/receipts.sqlite
python3 collector.py export --db spool/receipts.sqlite --out spool/ready --batch-rows 500
```

The journal is an on-disk SQLite database. Complete frames and observed malformed/truncated fragments are committed before export. The exporter creates newline-delimited JSON files in `spool/ready`. A temporary `.tmp` file is closed before becoming a `.jsonl` file. Export ranges are saved in the journal, so rerunning export reproduces the same completed filenames and bytes. New arrivals get new files. Existing files with different bytes cause an error.

You may export again while the collector is running; only one exporter should run at once. For week one, trigger it manually. The starter batches by at most 500 receipt records, not by exactly five event-time minutes. Its batch size is configurable. Preserve the journal and originals; do not delete them simply because an upload command returned successfully.

Open a JSON line. Find `raw_text`, `raw_frame_b64`, `fields`, `receipt_id`, `received_at_utc`, `replay_run_id` and `parse_error`. `raw_frame_b64` preserves exact bytes even if they are not valid ASCII. `fields` holds strings. A parsing error remains an inspectable record, not a silently dropped measurement.

## 6. Move completed files to Databricks

Begin with Catalog Explorer: choose a Unity Catalog volume and upload only completed `*.jsonl` files into its `wits` directory. Upload after the local export has completed, then run ingestion after the upload has completed. This is an intentional manual handoff for the first demo.

If you have the required permissions, these are example SQL objects; change `main` to your available catalog. See the [CREATE VOLUME syntax and requirements](https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-syntax-ddl-create-volume):

```sql
CREATE SCHEMA IF NOT EXISTS main.frac_demo;
CREATE VOLUME IF NOT EXISTS main.frac_demo.landing;
```

Alternatively use the [current Databricks CLI](https://docs.databricks.com/aws/en/dev-tools/cli/install) with [OAuth login](https://docs.databricks.com/aws/en/dev-tools/auth/oauth-u2m). Replace the host and the batch filename with real values:

```bash
databricks auth login --host https://YOUR_WORKSPACE_HOST --profile frac-demo
databricks fs mkdir dbfs:/Volumes/main/frac_demo/landing/wits --profile frac-demo
databricks fs cp spool/ready/ACTUAL_BATCH_FILENAME.jsonl dbfs:/Volumes/main/frac_demo/landing/wits/ACTUAL_BATCH_FILENAME.jsonl --profile frac-demo
databricks fs ls dbfs:/Volumes/main/frac_demo/landing/wits --profile frac-demo
```

Use the original completed filename, avoid overwrite, and retain local files for reconciliation. A filename-exists response needs verification, not automatic renaming or overwriting. Do not copy the SQLite database, `.tmp` files, manifests or credentials into the watched directory. See [CLI file commands](https://docs.databricks.com/aws/en/dev-tools/cli/reference/fs-commands) and [volume file handling](https://docs.databricks.com/aws/en/volumes/volume-files).

## 7. Ingest Bronze

Import `databricks/01_ingest_bronze.py` as a Databricks notebook. Edit its catalog, schema and volume settings to match Step 6, then run it on compatible compute. It uses an explicit envelope schema, captures file provenance, and appends with an Auto Loader checkpoint and an AvailableNow trigger. A rescue column retains unexpected JSON fields/type mismatches for review.

This template has not been run in your workspace. Workspace permissions, compute, volume access and Auto Loader support must be checked there. If setup takes more than 30 minutes, use the main guide's batch ingestion fallback and explain it in your demo.

Run it again with no new files. Bronze's row count should not change. Keep the checkpoint for this source/table combination. Do not delete it as a way to retry a failed run.

## 8. Prove delivery and build Silver

First compare DISTINCT `(source_sample_id, expected payload hash)` values in `data/expected_demo01.jsonl` with received `fields['9908']` and `raw_sha256` for `demo01`. Check missing and unexpected IDs and conflicting payloads. Counts alone can hide a missing record plus a duplicate.

Then follow Section 8 of the main guide: validate the custom mapping, cast measurements, keep per-channel quality flags, quarantine bad metadata/conflicting identities, and deduplicate within the run. Bronze retains repeated receipts; Silver holds the measurement interpretation. Do not turn null rates into zero or carry forward missing channels automatically.

Repeat Step 4 with the same input, export again and ingest the new file. Bronze should contain another receipt for each repeated transmission. Silver's unique measurement count and final Gold totals should remain unchanged. This proves your deduplication logic; the bundled transport tests do not prove that your unbuilt Silver/Gold implementation is correct.

## Troubleshooting

| Symptom | First check |
|---|---|
| Connection refused | Start the collector first; confirm both use the same port on the same computer. |
| Address already in use | Stop the previous collector or select another matching port in both commands. |
| Timestamp rejected | Confirm the source zone, then export a timezone-aware ISO timestamp. |
| No frames appear yet | A real source gap is preserved by replay; inspect times or use speed 0 for a functional test. |
| Blank optional field | Expected: the field is omitted, not set to zero. |
| `parse_error` set | Inspect preserved raw bytes and the CRLF/channel contract before changing the parser. |
| More Bronze rows than source rows | A retry or repeated replay creates multiple receipts; compare identities before declaring loss or duplication in Silver. |
| Volume permission error | Verify access to the chosen catalog/schema/volume and compute with its owner. |
| Old measurement dates | Correct for historical replay; inspect receipt and ingestion times for current pipeline freshness. |

## What is and is not finished

The local transport starter was tested with synthetic fixtures, including an actual TCP exchange, byte fragmentation, repeated delivery, malformed records and journal/export restart behavior. Ten automated tests passed during preparation. The Databricks notebook is a template. Source workbook mapping, real-data reconciliation, Silver/Gold calculations and the scorecard are your week's implementation work.

No claim of general WITS device compatibility, end-to-end exactly-once delivery, authenticated field networking, or production deployment is made. Full snapshot record 99, string IDs, port and retry behavior are this project's explicit contract. Actual equipment may use different mappings, delimiters, connection roles and partial updates. See the main guide before connecting to anything outside this local exercise.
