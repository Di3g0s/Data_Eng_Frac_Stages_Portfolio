"""Synthetic transport tests, NOT Utah FORGE measurements or field validation."""
import base64
import csv
import hashlib
import json
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from journal import Journal
from replay import prepare
from wits import FrameDecoder, encode, event_time, parse, sample_id

SYNTHETIC = {"9901": "2024-01-01T00:00:00Z", "9902": "123.4",
             "9903": "10", "9904": "test-stage", "9905": "synthetic-test"}


class FramingTests(unittest.TestCase):
    def test_fragmented_and_coalesced_tcp_input(self):
        frame = encode(SYNTHETIC)
        decoder = FrameDecoder()
        received = []
        for byte in frame + frame:
            received += decoder.feed(bytes([byte]))
        self.assertEqual(received, [(frame, None), (frame, None)])
        self.assertEqual(decoder.finish(), [])
        self.assertEqual(FrameDecoder().feed(frame + frame), received)

    def test_lost_tail_is_not_a_complete_record(self):
        decoder = FrameDecoder()
        self.assertEqual(decoder.feed(b"&&\r\n9902 1\r\n"), [])
        self.assertEqual(decoder.finish()[0][1], "connection_ended_mid_frame")

    def test_new_start_resynchronizes_and_preserves_partial(self):
        decoder = FrameDecoder()
        good = encode(SYNTHETIC)
        records = decoder.feed(b"&&\r\n9902 1\r\n" + good)
        self.assertEqual(records[0][1], "new_start_before_end")
        self.assertEqual(records[1], (good, None))

    def test_unterminated_buffer_is_bounded(self):
        decoder = FrameDecoder(max_bytes=32)
        records = decoder.feed(b"x" * 40)
        self.assertEqual(records, [(b"x" * 40, "buffer_limit")])
        self.assertEqual(len(decoder.pending), 0)

    def test_repeated_channel_and_non_ascii_are_rejected(self):
        for frame in [b"&&\r\n9902 1\r\n9902 2\r\n!!\r\n", b"&&\r\n9902 \xff\r\n!!\r\n"]:
            with self.assertRaises(ValueError):
                parse(frame)

    def test_raw_strings_and_absent_channel_are_preserved(self):
        parsed = parse(encode({"9902": "NaN", "9999": "custom"}))
        self.assertEqual(parsed, {"9902": "NaN", "9999": "custom"})
        self.assertNotIn("9903", parsed)  # Missing isn't 0 or last-known.

    def test_naive_timestamps_fail_and_offsets_normalize(self):
        with self.assertRaises(ValueError):
            event_time("2024-01-01T00:00:00")
        self.assertEqual(event_time("2024-01-01T00:00:00-03:00").hour, 3)


class JournalTests(unittest.TestCase):
    def test_restart_export_repetition_conflict_and_raw_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frame = encode(SYNTHETIC)
            journal = Journal(root / "spool.sqlite")
            journal.record(frame, None, "test01", "connection1")
            journal.record(frame, None, "test01", "connection2")
            journal.record(b"&&\r\n9902 \xff\r\n!!\r\n", None, "test01", "connection2")
            paths = journal.export(root / "ready", batch_rows=2)
            before = {p.name: p.read_bytes() for p in paths}
            journal.close()
            journal = Journal(root / "spool.sqlite")
            after = {p.name: p.read_bytes() for p in journal.export(root / "ready")}
            self.assertEqual(before, after)
            rows = [json.loads(line) for body in before.values() for line in body.splitlines()]
            self.assertEqual(len(rows), 3)
            self.assertEqual(base64.b64decode(rows[0]["raw_frame_b64"]), frame)
            self.assertNotEqual(rows[0]["receipt_id"], rows[1]["receipt_id"])
            self.assertEqual(rows[0]["raw_sha256"], rows[1]["raw_sha256"])
            self.assertIsNotNone(rows[2]["parse_error"])
            journal.record(frame, None, "test01", "connection3")
            new_paths = journal.export(root / "ready")
            self.assertEqual(len(new_paths), 3)
            self.assertEqual({p.name: p.read_bytes() for p in paths}, before)
            # Local exported files can be recreated from the preserved journal.
            paths[0].unlink()
            journal.export(root / "ready")
            self.assertEqual(paths[0].read_bytes(), before[paths[0].name])
            paths[0].write_text("changed")
            with self.assertRaises(ValueError):
                journal.export(root / "ready")
            journal.close()

    def test_source_identity_distinguishes_rows_not_replay_time(self):
        one = sample_id("a" * 64, "sheet", 1, "well", "stage")
        self.assertEqual(one, sample_id("a" * 64, "sheet", 1, "well", "stage"))
        self.assertNotEqual(one, sample_id("a" * 64, "sheet", 2, "well", "stage"))


class EndToEndTests(unittest.TestCase):
    def test_actual_tcp_sender_collector_and_replay_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "SYNTHETIC_TEST_ONLY.txt"
            original.write_text("Synthetic transport fixture; not field data.")
            csv_path = root / "canonical.csv"
            header = ["well_id", "stage_id", "event_time_utc", "pressure_psi",
                      "clean_rate_bpm", "slurry_rate_bpm", "source_sheet", "source_row"]
            with csv_path.open("w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(header)
                for number in range(3):
                    writer.writerow(["TEST", "TEST", f"2024-01-01T00:00:0{number}Z",
                                     123, "", 10, "synthetic", number + 1])
            rows, source_sha = prepare(csv_path, original)
            self.assertEqual(source_sha, hashlib.sha256(original.read_bytes()).hexdigest())
            ids = {parse(frame)["9908"] for _, frame in rows}
            with socket.socket() as temporary_socket:
                temporary_socket.bind(("127.0.0.1", 0))
                port = temporary_socket.getsockname()[1]
            script_dir = Path(__file__).resolve().parent
            db = root / "receipts.sqlite"
            with (root / "collector.log").open("w") as log:
                process = subprocess.Popen([sys.executable, str(script_dir / "collector.py"),
                    "serve", "--db", str(db), "--port", str(port), "--run-id", "test01"],
                    stdout=log, stderr=subprocess.STDOUT)
                try:
                    deadline = time.monotonic() + 8
                    while True:
                        try:
                            with socket.create_connection(("127.0.0.1", port), timeout=.2):
                                break
                        except OSError:
                            if time.monotonic() > deadline or process.poll() is not None:
                                self.fail((root / "collector.log").read_text())
                            time.sleep(.05)
                    for _ in range(2):
                        subprocess.run([sys.executable, str(script_dir / "replay.py"),
                            "--csv", str(csv_path), "--original", str(original),
                            "--port", str(port), "--speed", "0",
                            "--manifest", str(root / "expected.jsonl")],
                            check=True, capture_output=True, timeout=10)
                    journal = Journal(db)
                    try:
                        while journal.db.execute("SELECT count(*) FROM receipts").fetchone()[0] < 6:
                            if time.monotonic() > deadline:
                                self.fail("Collector did not journal all synthetic frames")
                            time.sleep(.05)
                        paths = journal.export(root / "ready")
                        envelopes = [json.loads(line) for p in paths for line in p.read_text().splitlines()]
                    finally:
                        journal.close()
                    self.assertEqual(len(envelopes), 6)
                    self.assertEqual({x["fields"]["9908"] for x in envelopes}, ids)
                    self.assertTrue(all(x["parse_error"] is None for x in envelopes))
                    expected = [json.loads(line) for line in (root / "expected.jsonl").read_text().splitlines()]
                    self.assertEqual({(r["source_sample_id"], r["expected_raw_sha256"]) for r in expected},
                                     {(r["fields"]["9908"], r["raw_sha256"]) for r in envelopes})
                finally:
                    process.terminate()
                    process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
