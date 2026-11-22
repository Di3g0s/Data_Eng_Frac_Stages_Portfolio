"""Replay your prepared real-data CSV to the LOCAL collector. No field data bundled."""
import argparse
import csv
import hashlib
import json
import math
import socket
import sys
import time
from pathlib import Path
from wits import CHANNELS, PROFILE, encode, event_time, parse, sample_id

REQUIRED = {"well_id", "stage_id", "event_time_utc", "pressure_psi",
            "source_sheet", "source_row"}


def prepare(csv_path, original_path, max_rows=None):
    # One original workbook/CSV per invocation. Preserve it alongside the CSV.
    source_sha = hashlib.sha256(Path(original_path).read_bytes()).hexdigest()
    rows = []
    with open(csv_path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        headers = set(reader.fieldnames or [])
        if not REQUIRED <= headers or not {"clean_rate_bpm", "slurry_rate_bpm"} & headers:
            raise ValueError("Use the canonical CSV header in README.md")
        for number, row in enumerate(reader, start=2):
            if max_rows is not None and len(rows) >= max_rows:
                break
            if None in row:
                raise ValueError(f"CSV line {number}: too many columns")
            row = {k: (v or "").strip() for k, v in row.items()}
            for key in ["well_id", "stage_id", "source_sheet", "source_row"]:
                if not row[key]:
                    raise ValueError(f"CSV line {number}: missing {key}")
            if not row["source_row"].isdigit() or int(row["source_row"]) < 1:
                raise ValueError(f"CSV line {number}: source_row must be a positive original row number")
            row["source_row"] = str(int(row["source_row"]))
            timestamp = event_time(row["event_time_utc"])
            identity = sample_id(source_sha, row["source_sheet"], row["source_row"],
                                 row["well_id"], row["stage_id"])
            fields = {"9901": timestamp.isoformat().replace("+00:00", "Z"),
                      "9904": row["stage_id"], "9905": row["well_id"],
                      "9908": identity, "9909": PROFILE, "9910": source_sha,
                      "9911": row["source_sheet"], "9912": row["source_row"]}
            for code, key in [("9902", "pressure_psi"), ("9903", "slurry_rate_bpm"),
                              ("9906", "clean_rate_bpm")]:
                if row.get(key):
                    fields[code] = row[key]  # Raw numeric strings; don't hide bad readings.
            rows.append((timestamp, encode(fields)))
    rows.sort(key=lambda item: item[0])  # Python sort is stable for equal times.
    if not rows:
        raise ValueError("CSV has no measurement rows")
    return rows, source_sha


def send(rows, port, speed, attempts=5):
    """Retry the complete selected input after a connection failure.

    Repetition is intentional and identities stay stable. No application ACK:
    sendall success does NOT prove that the collector durably saved every row.
    """
    for attempt in range(attempts):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
                started = time.monotonic()
                first_time = rows[0][0]
                for timestamp, frame in rows:
                    delay = ((timestamp - first_time).total_seconds() / speed
                             - (time.monotonic() - started)) if speed else 0
                    if delay > 0:
                        time.sleep(delay)
                    sock.sendall(frame)
                sock.shutdown(socket.SHUT_WR)
            print(json.dumps({"event": "send_finished", "rows_attempted": len(rows),
                              "durable_receipt_confirmed": False}), flush=True)
            return
        except OSError as exc:
            print(json.dumps({"event": "connection_failure", "attempt": attempt + 1,
                              "detail": str(exc), "action": "retry_entire_input"}), flush=True)
            if attempt + 1 == attempts:
                raise
            time.sleep(min(2 ** attempt, 8))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True)
    parser.add_argument("--original", required=True, help="Actual source workbook or source CSV")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--speed", type=float, default=10, help="10=10x, 1=original timing, 0=as fast as possible")
    parser.add_argument("--max-rows", type=int, help="Prefix of prepared CSV, for an initial small run")
    parser.add_argument("--check-only", action="store_true", help="Validate and print one actual encoded frame; no network")
    parser.add_argument("--manifest", help="Write expected identities/provenance for receipt reconciliation")
    args = parser.parse_args()
    if not math.isfinite(args.speed) or args.speed < 0:
        parser.error("speed must be finite and nonnegative")
    if args.max_rows is not None and args.max_rows < 1:
        parser.error("max-rows must be positive")
    rows, source_sha = prepare(args.csv, args.original, args.max_rows)
    print(json.dumps({"event": "prepared", "rows": len(rows), "source_sha256": source_sha,
                      "mapping_version": PROFILE}), flush=True)
    if args.manifest:
        destination = Path(args.manifest)
        if destination.resolve() in {Path(args.csv).resolve(), Path(args.original).resolve()}:
            parser.error("Manifest must not overwrite either input")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8") as handle:
            for _, frame in rows:
                record = {CHANNELS.get(code, code): value for code, value in parse(frame).items()}
                record["source_file_name"] = Path(args.original).name
                record["expected_raw_sha256"] = hashlib.sha256(frame).hexdigest()
                handle.write(json.dumps(record, sort_keys=True) + "\n")
    if args.check_only:
        print(rows[0][1].decode("ascii"))
    else:
        send(rows, args.port, args.speed)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        sys.exit(str(exc))
