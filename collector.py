"""Local WITS receiver. Run 'serve' in one terminal; 'export' in another."""
import argparse
import json
import socket
import uuid
from journal import Journal
from wits import FrameDecoder, utc_now


def log(event, **values):
    print(json.dumps({"time": utc_now(), "event": event, **values}), flush=True)


def serve(journal, port, run_id):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", port))  # Deliberately local-only; no public listener.
        listener.listen(1)
        listener.settimeout(1)
        log("listening", address="127.0.0.1", port=port, run_id=run_id)
        while True:
            try:
                connection, _ = listener.accept()
            except socket.timeout:
                continue
            connection_id = uuid.uuid4().hex
            decoder = FrameDecoder()
            log("connected", connection_id=connection_id)
            with connection:
                connection.settimeout(1)
                try:
                    while True:
                        try:
                            chunk = connection.recv(4096)
                        except socket.timeout:
                            continue
                        if not chunk:
                            break
                        for raw, error in decoder.feed(chunk):
                            receipt = journal.record(raw, error, run_id, connection_id)
                            log("journaled", receipt_number=receipt, framing_error=error)
                except (ConnectionError, TimeoutError) as exc:
                    log("disconnected_with_error", detail=str(exc))
                finally:
                    for raw, error in decoder.finish():
                        journal.record(raw, error, run_id, connection_id)
                    log("connection_closed", connection_id=connection_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ["serve", "export", "inspect"]:
        action = sub.add_parser(name)
        action.add_argument("--db", default="spool/receipts.sqlite")
        if name == "serve":
            action.add_argument("--port", type=int, default=9000)
            action.add_argument("--run-id", default="demo01")
        elif name == "export":
            action.add_argument("--out", default="spool/ready")
            action.add_argument("--batch-rows", type=int, default=500)
    args = parser.parse_args()
    journal = Journal(args.db)
    try:
        if args.command == "serve":
            serve(journal, args.port, args.run_id)
        elif args.command == "export":
            paths = journal.export(args.out, args.batch_rows)
            log("export_complete", completed_files=len(paths), directory=args.out)
        else:
            row = journal.db.execute("SELECT count(*) AS receipts, max(received_at_utc) AS last_received FROM receipts").fetchone()
            log("journal_summary", collection_id=journal.collection_id, **dict(row))
    except KeyboardInterrupt:
        log("stopped")
    finally:
        journal.close()


if __name__ == "__main__":
    main()
