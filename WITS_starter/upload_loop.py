"""Poll local exported receipts and verify each Databricks Volume upload by hash.

Personal SDK/CLI profiles remain supported; unattended jobs can use OAuth M2M
through DATABRICKS_HOST, DATABRICKS_CLIENT_ID and DATABRICKS_CLIENT_SECRET.
"""
import argparse
import hashlib
import io
import os
import time
from contextlib import closing
from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound
from journal import Journal

DEFAULT_DESTINATION = "/Volumes/main/frac_demo/landing/wits"
ROOT = Path(__file__).resolve().parent


class ContentConflict(Exception):
    """A destination already exists but contains different bytes."""


def make_client(profile=None):
    if profile:
        return WorkspaceClient(profile=profile)
    if os.getenv("DATABRICKS_HOST") and (
        os.getenv("DATABRICKS_CLIENT_ID") or os.getenv("DATABRICKS_TOKEN")
    ):
        # SDK unified authentication: PAT or service-principal OAuth M2M.
        return WorkspaceClient()
    # Backward-compatible with the Codespace profile used for initial testing.
    return WorkspaceClient(profile="frac-demo")


def upload_cycle(client, journal, ready, destination, confirmed):
    """One finite cycle; confirmed hashes are only an in-process optimization."""
    files = journal.export(ready, batch_rows=500)
    failures = []
    for file in files:
        payload = file.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if confirmed.get(file.name) == digest:
            continue
        remote_path = f"{destination.rstrip('/')}/{file.name}"
        try:
            try:
                response = client.files.download(remote_path)
            except NotFound:
                client.files.upload(remote_path, io.BytesIO(payload), overwrite=False)
                response = client.files.download(remote_path)
            with closing(response.contents) as stream:
                remote_digest = hashlib.sha256(stream.read()).hexdigest()
            if remote_digest != digest:
                raise ContentConflict(f"Different content already exists: {remote_path}")
            confirmed[file.name] = digest
            print(f"Confirmed upload: {file.name}", flush=True)
        except ContentConflict:
            raise
        except Exception as exc:
            # Do not mark a file as delivered when remote confirmation failed.
            failures.append(file.name)
            print(f"Upload not confirmed; retry next cycle: {file.name}: {exc}", flush=True)
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=os.getenv("DATABRICKS_CONFIG_PROFILE"),
                        help="Databricks config profile (default: frac-demo unless env OAuth credentials exist)")
    parser.add_argument("--destination", default=os.getenv("WITS_DESTINATION", DEFAULT_DESTINATION))
    parser.add_argument("--interval", type=int, default=int(os.getenv("WITS_UPLOAD_INTERVAL_SECONDS", "30")))
    parser.add_argument("--once", action="store_true", help="Perform one upload cycle and exit")
    args = parser.parse_args()
    if args.interval < 1:
        parser.error("--interval must be a positive integer")
    if not args.destination.startswith("/Volumes/"):
        parser.error("--destination must be an absolute Unity Catalog Volume path")

    client = make_client(args.profile)
    client.files.create_directory(args.destination)
    journal = Journal(ROOT / "spool" / "receipts.sqlite")
    confirmed = {}
    try:
        while True:
            failures = upload_cycle(client, journal, ROOT / "spool" / "ready", args.destination, confirmed)
            if args.once:
                if failures:
                    parser.exit(1, f"Upload incomplete: {len(failures)} file(s) unconfirmed\n")
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Uploader stopped.")
    finally:
        journal.close()


if __name__ == "__main__":
    main()
