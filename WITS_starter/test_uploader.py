"""Offline uploader tests using a fake Files API; no Databricks credentials."""
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from journal import Journal
from upload_loop import ContentConflict, upload_cycle
from wits import encode


class FakeFiles:
    def __init__(self, content):
        self.content = content
        self.download_calls = 0

    def download(self, path):
        self.download_calls += 1
        return SimpleNamespace(contents=io.BytesIO(self.content))


class UploadTests(unittest.TestCase):
    def test_existing_identical_remote_file_and_in_process_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            journal = Journal(root / "receipts.sqlite")
            try:
                journal.record(encode({"9902": "123"}), None, "test", "conn")
                ready = root / "ready"
                local_file = journal.export(ready)[0]
                client = SimpleNamespace(files=FakeFiles(local_file.read_bytes()))
                confirmed = {}
                self.assertEqual(upload_cycle(client, journal, ready, "/Volumes/main/frac_demo/landing/wits", confirmed), [])
                upload_cycle(client, journal, ready, "/Volumes/main/frac_demo/landing/wits", confirmed)
                self.assertEqual(client.files.download_calls, 1)
                self.assertIn(local_file.name, confirmed)
            finally:
                journal.close()

    def test_existing_remote_content_conflict_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            journal = Journal(root / "receipts.sqlite")
            try:
                journal.record(encode({"9902": "123"}), None, "test", "conn")
                client = SimpleNamespace(files=FakeFiles(b"wrong content"))
                with self.assertRaises(ContentConflict):
                    upload_cycle(client, journal, root / "ready",
                                 "/Volumes/main/frac_demo/landing/wits", {})
            finally:
                journal.close()


if __name__ == "__main__":
    unittest.main()
