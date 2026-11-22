import json
from pathlib import Path

rows = []
for file in sorted(Path("spool/ready").glob("*.jsonl")):
   with file.open() as f:
       rows.extend(json.loads(line) for line in f if line.strip())
valid = [
   r for r in rows
   if not r.get("parse_error") and r.get("fields", {}).get("9908")
]
identities = {
   (r.get("replay_run_id"), r["fields"].get("9909"), r["fields"]["9908"])
   for r in valid
}
print("Exported receipts:", len(rows))
print("Receipts with parsing errors:",
     sum(bool(r.get("parse_error")) for r in rows))
print("Distinct source identities across runs:", len(identities))
if valid:
   sample = valid[0]
   print("\nReceived at:", sample["received_at_utc"])
   print("Replay run:", sample["replay_run_id"])
   print("\nActual received WITS message:")
   print(sample["raw_text"])
else:
   print("No successfully parsed messages with source IDs found.")