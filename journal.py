"""Durable local receipt journal and repeatable, closed-file export.

SQLite commits protect received records on local disk, not an unreceived TCP
tail or loss of the computer. One collector and one exporter at a time.
"""
import base64
import hashlib
import json
import os
import sqlite3
import uuid
from pathlib import Path
from wits import parse, utc_now


class Journal:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS receipts (
              id INTEGER PRIMARY KEY, received_at_utc TEXT NOT NULL,
              replay_run_id TEXT NOT NULL, connection_id TEXT NOT NULL,
              raw BLOB NOT NULL, framing_error TEXT);
            CREATE TABLE IF NOT EXISTS exports (
              first_id INTEGER PRIMARY KEY, last_id INTEGER NOT NULL, filename TEXT NOT NULL);
        """)
        self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('collection_id', ?)",
                        (uuid.uuid4().hex,))
        self.db.commit()
        self.collection_id = self.db.execute("SELECT value FROM metadata WHERE key='collection_id'").fetchone()[0]

    def close(self):
        self.db.close()

    def record(self, raw, framing_error, run_id, connection_id):
        with self.db:
            result = self.db.execute("""INSERT INTO receipts
              (received_at_utc, replay_run_id, connection_id, raw, framing_error)
              VALUES (?, ?, ?, ?, ?)""", (utc_now(), run_id, connection_id, raw, framing_error))
        return result.lastrowid

    def envelope(self, row):
        raw = row["raw"]
        error = row["framing_error"]
        fields = {}
        if not error:
            try:
                fields = parse(raw)
            except ValueError as exc:
                error = str(exc)
        return {"envelope_version": "1", "receipt_id": f"{self.collection_id}:{row['id']}",
                "received_at_utc": row["received_at_utc"], "replay_run_id": row["replay_run_id"],
                "connection_id": row["connection_id"],
                "raw_frame_b64": base64.b64encode(raw).decode("ascii"),
                "raw_text": raw.decode("ascii", errors="replace"),
                "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "fields": fields, "parse_error": error}

    def export(self, directory, batch_rows=500):
        if batch_rows < 1:
            raise ValueError("batch_rows must be positive")
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        # Assign durable ranges first. A restart recreates the exact same names.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            last = self.db.execute("SELECT coalesce(max(last_id), 0) FROM exports").fetchone()[0]
            highest = self.db.execute("SELECT coalesce(max(id), 0) FROM receipts").fetchone()[0]
            while last < highest:
                end = min(last + batch_rows, highest)
                filename = f"{self.collection_id}_{last + 1:09d}_{end:09d}.jsonl"
                self.db.execute("INSERT INTO exports VALUES (?, ?, ?)", (last + 1, end, filename))
                last = end
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        paths = []
        for batch in self.db.execute("SELECT * FROM exports ORDER BY first_id").fetchall():
            rows = self.db.execute("SELECT * FROM receipts WHERE id BETWEEN ? AND ? ORDER BY id",
                                   (batch["first_id"], batch["last_id"])).fetchall()
            body = "".join(json.dumps(self.envelope(row), sort_keys=True, ensure_ascii=True)
                           + "\n" for row in rows).encode("utf-8")
            target = directory / batch["filename"]
            if target.exists():
                if target.read_bytes() != body:
                    raise ValueError(f"Existing completed file has different bytes: {target}")
            else:
                # Only *.jsonl files may be copied to the ingestion landing area.
                temp = directory / (batch["filename"] + ".tmp")
                with temp.open("wb") as handle:
                    handle.write(body)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp, target)
                if os.name == "posix":
                    descriptor = os.open(directory, os.O_RDONLY)
                    try:
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
            paths.append(target)
        return paths
