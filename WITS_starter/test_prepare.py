"""Synthetic spreadsheet-adapter tests, not field-data validation."""
import csv
import importlib.util
import tempfile
import unittest
from datetime import datetime, time
from pathlib import Path

import pandas as pd

SOURCE = Path(__file__).resolve().parent / "data" / "raw_2_prepared.py"
spec = importlib.util.spec_from_file_location("raw_2_prepared", SOURCE)
converter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(converter)


class PreparationTests(unittest.TestCase):
    def test_original_excel_row_numbers(self):
        self.assertEqual(converter.source_row_number(5), 6)
        self.assertEqual(converter.source_row_number(10), 11)

    def test_existing_csv_cannot_be_overwritten_by_default(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = root / "Stage 1.xlsx"
            target = root / "canonical.csv"
            target.write_text("my previous data", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                converter.convert_workbook(original, target, "WELL")
            self.assertEqual(target.read_text(encoding="utf-8"), "my previous data")

    def test_stage_is_inferred_not_hardcoded(self):
        self.assertEqual(converter.stage_from_filename(Path("16B(78)-32_Stage 2_Treatment Data.xlsx")), "2")
        self.assertEqual(converter.stage_from_filename(Path("Stage-12.xlsx")), "12")
        with self.assertRaises(ValueError):
            converter.stage_from_filename(Path("unknown.xlsx"))

    def test_multiple_originals_require_explicit_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            raw = Path(folder)
            (raw / "Stage 1.xlsx").touch()
            (raw / "Stage 2.xlsx").touch()
            with self.assertRaisesRegex(ValueError, "Multiple originals"):
                converter.choose_one_workbook(None, raw)

    def test_one_source_spreadsheet_preserves_physical_row_and_stage(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workbook = root / "16B(78)-32_Stage 2_Treatment Data.xlsx"
            # Five header rows, then physical Excel row six is the measurement.
            content = [["header", None, None, None, None, None, None] for _ in range(5)]
            content.append([datetime(2024, 4, 5), time(12, 30), 1500, None, 10, None, 8])
            pd.DataFrame(content).to_excel(workbook, index=False, header=False)
            csv_path = root / "stage2.csv"
            self.assertEqual(converter.convert_workbook(workbook, csv_path, "TEST-WELL"), 1)
            with csv_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["stage_id"], "2")
            self.assertEqual(rows[0]["source_row"], "6")
            self.assertEqual(rows[0]["well_id"], "TEST-WELL")
            self.assertEqual(rows[0]["event_time_utc"], "2024-04-05T12:30:00Z")
            self.assertEqual(rows[0]["pressure_psi"], "1500")


if __name__ == "__main__":
    unittest.main()
