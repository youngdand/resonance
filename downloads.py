"""Durable queue intent, transactional reservations and conservative reconciliation."""

import json, time, uuid, threading, math
from urllib.parse import quote
from transfer_state import classify

lock = threading.RLock()


def validate(file):
    if not isinstance(file, dict) or not file.get("username") or not file.get("filename"):
        raise ValueError("Choose a valid peer file.")
    size = file.get("size")
    if (
        isinstance(size, bool)
        or not isinstance(size, (int, float))
        or not math.isfinite(size)
        or size < 0
    ):
        raise ValueError("File size must be a nonnegative number.")


def reserve(s, record, c=None):
    if c is None:
        with s.db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return reserve(s, record, connection)
    file = record["file"]
    key = (file["username"], file["filename"])
    existing = c.execute(
        "SELECT request_id FROM queue_keys WHERE username=? AND filename=?", key
    ).fetchone()
    if existing:
        row = c.execute("SELECT value FROM requests WHERE id=?", (existing[0],)).fetchone()
        if row:
            prior = json.loads(row[0])
            if classify(prior["status"]) not in ("cancelled", "replaced"):
                return prior
        c.execute("DELETE FROM queue_keys WHERE username=? AND filename=?", key)
    # Adopt requests from older installations as well as new transactional reservations.
    for row in c.execute("SELECT value FROM requests"):
        prior = json.loads(row[0])
        f = prior["file"]
        if (f["username"], f["filename"]) == key and classify(prior["status"]) not in (
            "cancelled",
            "replaced",
        ):
            c.execute("INSERT OR REPLACE INTO queue_keys VALUES (?,?,?)", (*key, prior["id"]))
            return prior
    c.execute("INSERT INTO requests VALUES (?,?)", (record["id"], json.dumps(record)))
    c.execute("INSERT INTO queue_keys VALUES (?,?,?)", (*key, record["id"]))
    return record


def submit(s, record):
    file = record["file"]
    body = {
        "id": record["batchId"],
        "username": file["username"],
        "files": [{"filename": file["filename"], "size": file["size"]}],
        "options": {},
    }
    if record.get("destination"):
        body["options"]["destination"] = record["destination"]
    try:
        response = s.slsk("transfers/downloads/batches", "POST", body)
        if not isinstance(response, dict) or not (
            response.get("batch", {}).get("id") or response.get("enqueued")
        ):
            raise ValueError("The engine did not confirm acceptance.")
        record["status"] = (
            "Enqueue failed"
            if any(f.get("filename") == file["filename"] for f in response.get("failures", []))
            else "Queued"
        )
    except Exception as exc:
        record["status"] = "Unconfirmed"
        record["lastError"] = "The engine response was not confirmed. Reconcile before retrying."
        s.diag.error(exc, operation="queue-submit")
    record["lastAttempt"] = time.time()
    s.save_request(record)
    if record.get("replaces") and record["status"] == "Queued":
        finish_replacement(s, record)
    return record


def finish_replacement(s, record):
    with s.db() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT value FROM requests WHERE id=?", (record["replaces"],)).fetchone()
        if row:
            prior = json.loads(row[0])
            prior["status"] = "Replaced"
            c.execute(
                "UPDATE requests SET value=? WHERE id=?",
                (json.dumps(prior), prior["id"]),
            )
    import album_jobs

    album_jobs.replace_request(s, record["replaces"], record["id"], record)


def queue(s, file, query, replaces=None, album_root=None):
    validate(file)
    with lock:
        with s.db() as c:
            prior = (
                c.execute("SELECT value FROM requests WHERE id=?", (replaces,)).fetchone()
                if replaces
                else None
            )
        prior = json.loads(prior[0]) if prior else None
        if replaces and (not prior or classify(prior["status"]) != "failed"):
            raise ValueError("Reconcile first. Only confirmed failed requests can change source.")
        import album_jobs

        destination = prior.get("destination") if prior else None
        if not destination and prior:
            destination = album_jobs.request_destination(s, prior["id"])
        if album_root and not destination:
            destination = album_jobs.destination(album_root, file["filename"])
        ident = str(uuid.uuid4())
        record = {
            "id": ident,
            "batchId": ident,
            "query": str(query)[:1000],
            "file": dict(file),
            "status": "Unconfirmed",
            "created": time.time(),
            "replaces": replaces,
            "attempts": prior.get("attempts", []) + [prior["file"]] if prior else [],
        }
        if prior and prior.get("jobId"):
            record["jobId"] = prior["jobId"]
        if destination:
            record["destination"] = destination
        stored = reserve(s, record)
        if stored["id"] != ident:
            return stored
    return submit(s, record)


def retry(s, ident):
    with lock:
        with s.db() as c:
            row = c.execute("SELECT value FROM requests WHERE id=?", (ident,)).fetchone()
        if not row:
            raise ValueError("Request not found.")
        record = json.loads(row[0])
        if classify(record["status"]) != "uncertain":
            return record
        # Engine batch GET distinguishes an accepted operation from an unreachable service.
        try:
            batch = s.slsk(
                "transfers/downloads/batches/" + quote(record.get("batchId", ident), safe="")
            )
        except Exception as exc:
            if getattr(exc, "status", None) != 404:
                return {
                    **record,
                    "lastError": "The engine is unavailable; acceptance is still uncertain.",
                }
            batch = None
        if batch:
            file = next(
                (
                    f
                    for f in batch.get("transfers", [])
                    if f.get("filename") == record["file"]["filename"]
                ),
                None,
            )
            if file:
                record.update(status=file.get("state", "Queued"), transferId=file.get("id"))
                s.save_request(record)
                if record.get("replaces"):
                    finish_replacement(s, record)
                return record
        # The same stable batch ID is safe whether an earlier response arrives late or not.
        return submit(s, record)
