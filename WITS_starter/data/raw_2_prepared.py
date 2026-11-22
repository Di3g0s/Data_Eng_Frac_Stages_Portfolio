from __future__ import annotations

import argparse
import csv
import re
from datetime import datetime, time, timedelta
from pathlib import Path

import pandas as pd


WELL_ID = "16B(78)-32"
STAGE_ID = 1


def combine_date_and_time(date_value: object, time_value: object) -> str:
    """Combine Excel date/time cells and return an ISO-8601 UTC timestamp."""
    if pd.isna(date_value) and pd.isna(time_value):
        return ""

    if isinstance(date_value, datetime):
        date_part = date_value.date()
    elif isinstance(date_value, pd.Timestamp):
        date_part = date_value.date()
    elif hasattr(date_value, "date"):
        date_part = date_value.date()
    else:
        date_text = str(date_value).strip()
        date_part = pd.to_datetime(date_text, errors="coerce")
        if pd.isna(date_part):
            raise ValueError(f"Invalid date value: {date_value!r}")
        date_part = date_part.date()

    if isinstance(time_value, datetime):
        time_part = time_value.time()
    elif isinstance(time_value, pd.Timestamp):
        time_part = time_value.time()
    elif isinstance(time_value, time):
        time_part = time_value
    elif pd.isna(time_value):
        time_part = time(0, 0)
    else:
        text = str(time_value).strip()
        parsed = pd.to_datetime(text, format=None, errors="coerce")
        if pd.isna(parsed):
            # Some spreadsheets store time as a fraction of a day.
            try:
                parsed = timedelta(days=float(text))
                seconds = parsed.seconds
                time_part = time(seconds // 3600, (seconds // 60) % 60, seconds % 60)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid time value: {time_value!r}")
        else:
            time_part = parsed.time()

    combined = datetime.combine(date_part, time_part)
    return combined.strftime("%Y-%m-%dT%H:%M:%SZ")


def numeric_value(value: object) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, (int, float)):
        if float(value).is_integer():
            return str(int(value))
    return str(value).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert WITS Excel files to canonical CSV format")
    parser.add_argument("--raw-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--header", type=Path)
    args = parser.parse_args()

    data_dir = Path(__file__).resolve().parent
    starter_dir = data_dir.parent
    raw_dir = args.raw_dir or data_dir / "raw"
    header_path = args.header or starter_dir / "canonical_header.csv"
    output_path = args.output or data_dir / "prepared/canonical.csv"

    with header_path.open("r", newline="", encoding="utf-8-sig") as handle:
        header_row = next(csv.reader(handle))

    required_header = [
        "well_id",
        "stage_id",
        "event_time_utc",
        "pressure_psi",
        "clean_rate_bpm",
        "slurry_rate_bpm",
        "source_sheet",
        "source_row",
    ]
    if header_row != required_header:
        raise ValueError(
            f"canonical_header.csv must contain exactly this header: {','.join(required_header)}"
        )

    excel_files = sorted(
        path for path in raw_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".xlsx", ".xls", ".xlsm"}
    ) if raw_dir.exists() else []

    if not excel_files:
        raise FileNotFoundError(f"No Excel files found in {raw_dir}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as output_handle:
        writer = csv.DictWriter(output_handle, fieldnames=required_header)
        writer.writeheader()

        for excel_path in excel_files:
            sheets = pd.read_excel(excel_path, sheet_name=None, header=None)
            for sheet_name, frame in sheets.items():
                # Excel row 6 is the first data row (0-based pandas row 5).
                for frame_row_number, row in frame.iloc[5:].iterrows():
                    if row.isna().all():
                        continue
                    source_row = 6 + int(frame_row_number)

                    writer.writerow({
                        "well_id": WELL_ID,
                        "stage_id": STAGE_ID,
                        "event_time_utc": combine_date_and_time(row.iloc[0], row.iloc[1]),
                        "pressure_psi": numeric_value(row.iloc[2]),
                        "clean_rate_bpm": numeric_value(row.iloc[6]),
                        "slurry_rate_bpm": numeric_value(row.iloc[4]),
                        "source_sheet": sheet_name,
                        "source_row": source_row,
                    })


if __name__ == "__main__":
    main()
