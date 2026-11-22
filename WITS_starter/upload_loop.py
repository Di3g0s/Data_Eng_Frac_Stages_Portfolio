import hashlib
import io
import time
from contextlib import closing
from pathlib import Path
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound
from journal import Journal

# Adjust these names to match the volume you created.
DESTINATION = "/Volumes/main/frac_demo/landing/wits"
INTERVAL_SECONDS = 30
ROOT = Path(__file__).resolve().parent
READY = ROOT / "spool" / "ready"
client = WorkspaceClient(profile="frac-demo")
client.files.create_directory(DESTINATION)
journal = Journal(ROOT / "spool" / "receipts.sqlite")
confirmed = {}

class ContentConflict(Exception):
   pass

try:
   while True:
       # Export only journaled receipts into completed files.
       files = journal.export(READY, batch_rows=500)
       for file in files:
           payload = file.read_bytes()
           digest = hashlib.sha256(payload).hexdigest()
           if confirmed.get(file.name) == digest:
               continue
           remote_path = f"{DESTINATION}/{file.name}"
           try:
               # On restart, check whether this file already exists.
               try:
                   response = client.files.download(remote_path)
               except NotFound:
                   client.files.upload(
                       remote_path,
                       io.BytesIO(payload),
                       overwrite=False,
                   )
                   response = client.files.download(remote_path)
               # Verify the saved bytes before recording success.
               with closing(response.contents) as stream:
                   remote_digest = hashlib.sha256(
                       stream.read()
                   ).hexdigest()
               if remote_digest != digest:
                   raise ContentConflict(
                       f"Different content already exists: {remote_path}"
                   )
               confirmed[file.name] = digest
               print(f"Confirmed upload: {file.name}", flush=True)
           except ContentConflict:
               raise
           except Exception as exc:
               print(
                   f"Upload not confirmed; retry next cycle: "
                   f"{file.name}: {exc}",
                   flush=True,
               )
       time.sleep(INTERVAL_SECONDS)
except KeyboardInterrupt:
   print("Uploader stopped.")
finally:
   journal.close()