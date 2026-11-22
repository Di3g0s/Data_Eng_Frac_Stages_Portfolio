"""Small, deliberately restricted WITS Level 0-style training profile.

Record 99 and these item meanings are OUR contract, not standard frac codes.
The profile uses ASCII, CRLF, one space after RRII, and full snapshots.
"""
import hashlib
import json
from datetime import datetime, timezone

PROFILE = "forge-frac-v1"
CHANNELS = {
    "9901": "event_time_utc",
    "9902": "pressure_psi",
    "9903": "slurry_rate_bpm",
    "9904": "stage_id",
    "9905": "well_id",
    "9906": "clean_rate_bpm",
    "9908": "source_sample_id",
    "9909": "mapping_version",
    "9910": "source_sha256",
    "9911": "source_sheet",
    "9912": "source_row",
}


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def event_time(value):
    value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp needs a documented time zone; naive time rejected")
    return value.astimezone(timezone.utc)


def sample_id(source_sha256, sheet, row, well, stage):
    # Delimited JSON avoids ambiguous concatenation. Arrival time is excluded.
    parts = [source_sha256, sheet, str(row), well, stage]
    return hashlib.sha256(json.dumps(parts, ensure_ascii=True).encode()).hexdigest()


def encode(fields):
    lines = [b"&&"]
    for code, value in sorted(fields.items()):
        if len(code) != 4 or not code.isascii() or not code.isdigit():
            raise ValueError("Channel codes must be four ASCII digits")
        value = str(value)
        if not value or value != value.strip():
            raise ValueError("Omit missing values; trim surrounding whitespace")
        if any(ord(c) < 32 or ord(c) > 126 for c in value):
            raise ValueError("This training profile accepts printable ASCII values only")
        lines.append((code + " " + value).encode("ascii"))
    return b"\r\n".join(lines + [b"!!", b""])


def parse(raw):
    """Keep strings here. Engineering casting and quality decisions belong in Silver."""
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("Non-ASCII payload") from exc
    lines = text.split("\r\n")
    if len(lines) < 4 or lines[0] != "&&" or lines[-2:] != ["!!", ""]:
        raise ValueError("Expected complete CRLF-delimited frame")
    fields = {}
    for line in lines[1:-2]:
        if len(line) < 6 or not line[:4].isdigit() or line[4] != " ":
            raise ValueError("Expected RRII, a space, and a value")
        code, value = line[:4], line[5:]
        if code in fields:
            raise ValueError("Repeated channel in one snapshot: " + code)
        if not value or value != value.strip() or any(ord(c) < 32 or ord(c) > 126 for c in value):
            raise ValueError("Invalid value formatting")
        fields[code] = value
    return fields


class FrameDecoder:
    """TCP has no message boundaries. Feed arbitrary chunks, get framed bytes.

    Returns (raw_bytes, framing_error_or_None). Bad/truncated bytes are returned
    too, so the collector can journal them instead of silently dropping them.
    """
    def __init__(self, max_bytes=65536):
        self.pending = bytearray()
        self.frame = bytearray()
        self.max_bytes = max_bytes

    def feed(self, data):
        self.pending.extend(data)
        results = []
        while b"\r\n" in self.pending:
            end = self.pending.index(b"\r\n") + 2
            line = bytes(self.pending[:end])
            del self.pending[:end]
            if line == b"&&\r\n":
                if self.frame:
                    results.append((bytes(self.frame), "new_start_before_end"))
                self.frame = bytearray(line)
            elif not self.frame:
                results.append((line, "bytes_outside_frame"))
            else:
                self.frame.extend(line)
                if len(self.frame) > self.max_bytes:
                    results.append((bytes(self.frame), "frame_too_large"))
                    self.frame.clear()
                elif line == b"!!\r\n":
                    results.append((bytes(self.frame), None))
                    self.frame.clear()
        if len(self.frame) + len(self.pending) > self.max_bytes:
            results.append((bytes(self.frame + self.pending), "buffer_limit"))
            self.frame.clear()
            self.pending.clear()
        return results

    def finish(self):
        remainder = bytes(self.frame + self.pending)
        self.frame.clear()
        self.pending.clear()
        return [(remainder, "connection_ended_mid_frame")] if remainder else []
