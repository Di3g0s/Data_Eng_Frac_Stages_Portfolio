"""Adapt one reviewed frac-treatment workbook to the canonical replay CSV.

Workbook-specific assumptions are documented in README_WITS.md. In particular,
this script assumes original timestamps are UTC; it does not infer time zones.
"""
from __future__ import annotations

import argparse
import csv
import re
from datetime import datetime, time, timedelta
from pathlib import Path

import pandas as pd

DEFAULT_WELL_ID = "16B(78)-32"
REQUIRED_HEADER = [
    "well_id", "stage_id", "event_time_utc", "pressure_psi",
    "clean_rate_bpm", "slurry_rate_bpm", "source_sheet", "source_row",
]


def source_row_number(frame_index: int) -> int:
    """A zero-based pandas row index maps to an Excel physical row with +1."""
    return int(frame_index) + 1


def stage_from_filename(path: Path) -> str:
    """Fail closed rather than silently labelling every workbook Stage 1."""
    match = re.search(r"(?:^|[_\s-])stage[_\s-]*(\d+)(?:[_\s-]|$)",
                      path.stem, flags=re.IGNORECASE)
    if not match:
        raise ValueError(f"Cannot infer stage number from {path.name!r}; expected 'Stage N'")
    return str(int(match.group(1)))


def combine_date_and_time(date_value: object, time_value: object) -> str:
    """Format the spreadsheet's presumed-UTC date/time as an ISO UTC string."""
    if pd.isna(date_value) and pd.isna(time_value):
        return ""

    if isinstance(date_value, (datetime, pd.Timestamp)):
        date_part = date_value.date()
    elif hasattr(date_value, "date"):
        date_part = date_value.date()
    else:
        parsed_date = pd.to_datetime(str(date_value).strip(), errors="coerce")
        if pd.isna(parsed_date):
            raise ValueError(f"Invalid date value: {date_value!r}")
        date_part = parsed_date.date()

    if isinstance(time_value, (datetime, pd.Timestamp)):
        time_part = time_value.time()
    elif isinstance(time_value, time):
        time_part = time_value
    elif pd.isna(time_value):
        time_part = time(0, 0)
    else:
        text = str(time_value).strip()
        parsed = pd.to_datetime(text, errors="coerce")
        if pd.isna(parsed):
            try:
                seconds = timedelta(days=float(text)).seconds
                time_part = time(seconds // 3600, (seconds // 60) % 60, seconds % 60)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid time value: {time_value!r}") from exc
        else:
            time_part = parsed.time()

    combined = datetime.combine(date_part, time_part)
    return combined.strftime("%Y-%m-%dT%H:%M:%SZ")


def numeric_value(value: object) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, (int, float)) and float(value).is_integer():
        return str(int(value))
    return str(value).strip()


def choose_one_workbook(raw_file: Path | None, raw_dir: Path) -> Path:
    if raw_file is not None:
        if not raw_file.is_file() or raw_file.suffix.lower() not in {".xlsx", ".xls", ".xlsm"}:
            raise FileNotFoundError(f"Excel workbook not found: {raw_file}")
        return raw_file
    excel_files = sorted(path for path in raw_dir.iterdir()
                         if path.is_file() and path.suffix.lower() in {".xlsx", ".xls", ".xlsm"}) \
                  if raw_dir.exists() else []
    if not excel_files:
        raise FileNotFoundError(f"No Excel workbooks found in {raw_dir}")
    if len(excel_files) > 1:
        raise ValueError("Multiple originals found; select one with --raw-file so source hashes stay correct")
    return excel_files[0]


def convert_workbook(workbook: Path, output: Path, well_id: str, overwrite: bool = False) -> int:
    stage_id = stage_from_filename(workbook)
    if output.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing CSV: {output}. Use --overwrite explicitly.")
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output.open("w", newline="", encoding="utf-8") as output_handle:
        writer = csv.DictWriter(output_handle, fieldnames=REQUIRED_HEADER)
        writer.writeheader()
        for sheet_name, frame in pd.read_excel(workbook, sheet_name=None, header=None).items():
            # Excel rows 1-5: workbook-specific headings. Data start in row 6.
            for frame_index, row in frame.iloc[5:].iterrows():
                if row.isna().all():
                    continue
                if len(row) < 7:
                    raise ValueError(f"Expected >=7 workbook columns in {workbook.name}, sheet {sheet_name}")
                writer.writerow({
                    "well_id": well_id,
                    "stage_id": stage_id,
                    "event_time_utc": combine_date_and_time(row.iloc[0], row.iloc[1]),
                    "pressure_psi": numeric_value(row.iloc[2]),
                    "clean_rate_bpm": numeric_value(row.iloc[6]),
                    "slurry_rate_bpm": numeric_value(row.iloc[4]),
                    "source_sheet": sheet_name,
                    "source_row": source_row_number(frame_index),
                })
                count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-file", type=Path, help="Single source workbook for this replay")
    parser.add_argument("--raw-dir", type=Path, help="Directory when only one workbook exists")
    parser.add_argument("--output", type=Path, help="Target canonical CSV")
    parser.add_argument("--header", type=Path, help="Path to canonical_header.csv")
    parser.add_argument("--well-id", default=DEFAULT_WELL_ID)
    parser.add_argument("--overwrite", action="store_true", help="Explicitly overwrite output CSV")
    args = parser.parse_args()

    data_dir = Path(__file__).resolve().parent
    starter_dir = data_dir.parent
    header_path = args.header or starter_dir / "canonical_header.csv"
    with header_path.open("r", newline="", encoding="utf-8-sig") as handle:
        actual_header = next(csv.reader(handle))
    if actual_header != REQUIRED_HEADER:
        raise ValueError("canonical_header.csv does not match the required schema")
    source = choose_one_workbook(args.raw_file, args.raw_dir or data_dir / "raw")
    output = args.output or data_dir / "prepared" / f"stage{stage_from_filename(source)}.csv"
    count = convert_workbook(source, output, args.well_id, overwrite=args.overwrite)
    print(f"Prepared {count} rows from {source} (Stage {stage_from_filename(source)}) -> {output}")
    print("Verify original UTC assumption and source units before interpreting data.")


if __name__ == "__main__":
    main()
