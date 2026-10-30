"""Persistent album manifests layered over slskd batches and request history."""

from pathlib import PureWindowsPath
from urllib.parse import quote
import json, re, threading, time, uuid

lock = threading.RLock()


def store(s, job):
    with s.db() as c:
        c.execute(
            "INSERT OR REPLACE INTO album_jobs VALUES (?,?)",
            (job["id"], json.dumps(job)),
        )


def request_index(s):
    with s.db() as c:
        return {r["id"]: json.loads(r["value"]) for r in c.execute("SELECT id,value FROM requests")}


def summary(job, requests):
    files = []
    done = 0
    failed = 0
    bytes_done = 0
    total = 0
    speed = 0
    for item in job["files"]:
        r = requests.get(item["requestId"])
        state = (r or {}).get("status", item.get("status", "Unconfirmed"))
        size = (r or {}).get("file", item["file"])["size"]
        from transfer_state import succeeded

        ok = succeeded(state)
        done += int(ok)
        failed += int(
            bool(re.search(r"error|reject|denied|failed|cancel|unconfirmed", state, re.I))
        )
        if r and not re.search(
            r"completed|succeeded|errored|cancelled|rejected|queued", state, re.I
        ):
            speed += max(0, r.get("currentSpeed", r.get("averageSpeed", 0)) or 0)
        total += size
        bytes_done += size if ok else min(size, (r or {}).get("bytesTransferred", 0))
        files.append({**item, "status": state})
    status = (
        "Selected files complete"
        if files and done == len(files)
        else "Needs attention" if failed else "Downloading / queued"
    )
    archived = bool(files) and all(
        requests.get(x["requestId"], {}).get("archived", False) for x in files
    )
    return {
        **job,
        "files": files,
        "completed": done,
        "failed": failed,
        "expected": len(files),
        "bytesTransferred": bytes_done,
        "size": total,
        "currentSpeed": speed,
        "status": status,
        "archived": archived,
    }


def list_jobs(s):
    requests = request_index(s)
    with s.db() as c:
        jobs = [json.loads(r[0]) for r in c.execute("SELECT value FROM album_jobs")]
    return [summary(j, requests) for j in sorted(jobs, key=lambda j: j["created"], reverse=True)]


def destination(root, filename):
    # Never turn a peer-supplied path into a local absolute path or traversal.
    path = PureWindowsPath(filename)
    base = PureWindowsPath(root)
    if any(p in (".", "..") for p in filename.replace("\\", "/").split("/")):
        raise ValueError("Unsafe album file path.")
    try:
        relative = path.relative_to(base)
    except ValueError:
        raise ValueError("A selected file is outside this album folder.") from None
    parts = [base.name, *relative.parts[:-1]]
    if not base.name or not relative.name:
        raise ValueError("Invalid album folder.")
    return "/".join(re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", p).rstrip(" .") or "_" for p in parts)


def submit_groups(s, job, reconcile=False):
    from transfer_state import classify

    records = request_index(s)
    groups = {}
    for item in job["files"]:
        record = records.get(item["requestId"])
        if not record or classify(record["status"]) != "uncertain":
            continue
        groups.setdefault(
            (item.get("batchId", record.get("batchId")), item["destination"]), []
        ).append(item)
    for (batchid, target), items in groups.items():
        if not batchid:
            continue
        if reconcile:
            try:
                batch = s.slsk("transfers/downloads/batches/" + quote(batchid, safe=""))
            except Exception as exc:
                if getattr(exc, "status", None) != 404:
                    job["warnings"] = [
                        "Engine acceptance is still uncertain. Retry reconciliation when it is reachable."
                    ]
                    continue
                batch = None
            if batch:
                accepted = {f.get("filename"): f for f in batch.get("transfers", [])}
                remaining = []
                for item in items:
                    file = accepted.get(item["file"]["filename"])
                    if file:
                        record = records[item["requestId"]]
                        record.update(
                            status=file.get("state", "Queued"),
                            transferId=file.get("id"),
                        )
                        s.save_request(record)
                    else:
                        remaining.append(item)
                items = remaining
                if not items:
                    continue
        try:
            response = s.slsk(
                "transfers/downloads/batches",
                "POST",
                {
                    "id": batchid,
                    "username": job["username"],
                    "files": [
                        {"filename": x["file"]["filename"], "size": x["file"]["size"]}
                        for x in items
                    ],
                    "options": {"destination": target},
                },
            )
            if not isinstance(response, dict) or not response.get("batch", {}).get("id"):
                raise ValueError("Engine did not confirm the album batch.")
            failures = {x["filename"] for x in response.get("failures", [])}
            for item in items:
                record = records[item["requestId"]]
                record["status"] = (
                    "Enqueue failed" if item["file"]["filename"] in failures else "Queued"
                )
                s.save_request(record)
                item["status"] = record["status"]
        except Exception as exc:
            s.diag.error(exc, operation="album-batch-enqueue")
            job["warnings"] = [
                "Some files remain unconfirmed. Use Reconcile to check acceptance and retry missing work."
            ]
    store(s, job)
    return summary(job, request_index(s))


def enqueue(s, body):
    from features import user
    from downloads import reserve

    username = user(body.get("username"))
    root = str(body.get("directory", "")).replace("\\", "/").rstrip("/")
    try:
        jobid = str(uuid.UUID(str(body.get("id", ""))))
    except ValueError:
        raise ValueError("A valid album job ID is required.") from None
    files = body.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= 5000:
        raise ValueError("Choose between 1 and 5,000 album files.")
    normalized = []
    seen = set()
    for file in files:
        from downloads import validate

        validate(file)
        if file["username"] != username:
            raise ValueError("Choose one peer for an album.")
        target = destination(root, file["filename"])
        if file["filename"] in seen:
            raise ValueError("The same file was selected twice.")
        seen.add(file["filename"])
        normalized.append((dict(file), target))
    with lock:
        with s.db() as c:
            existing = c.execute("SELECT value FROM album_jobs WHERE id=?", (jobid,)).fetchone()
        if existing:
            job = json.loads(existing[0])
            if (
                job["username"] != username
                or job["directory"] != root
                or [x["file"]["filename"] for x in job["files"]]
                != [x[0]["filename"] for x in normalized]
            ):
                raise ValueError("This album ID belongs to a different selection.")
            if not any(
                x.get("status") == "Unconfirmed"
                for x in request_index(s).values()
                if x.get("jobId") == jobid
            ):
                return summary(job, request_index(s))
            return submit_groups(s, job, reconcile=True)
        job = {
            "id": jobid,
            "username": username,
            "directory": root,
            "query": str(body.get("query", ""))[:1000],
            "created": time.time(),
            "files": [],
            "warnings": [],
        }
        # Manifest and all reservations commit together before any network side effect.
        with s.db() as c:
            c.execute("BEGIN IMMEDIATE")
            for file, target in normalized:
                batchid = str(uuid.uuid5(uuid.UUID(jobid), target))
                rid = str(uuid.uuid4())
                record = reserve(
                    s,
                    {
                        "id": rid,
                        "query": job["query"],
                        "file": file,
                        "status": "Unconfirmed",
                        "created": job["created"],
                        "attempts": [],
                        "jobId": jobid,
                        "batchId": batchid,
                        "destination": target,
                    },
                    c,
                )
                job["files"].append(
                    {
                        "file": record["file"],
                        "requestId": record["id"],
                        "status": record["status"],
                        "destination": record.get("destination", target),
                        "batchId": record.get("batchId", batchid),
                    }
                )
            c.execute("INSERT INTO album_jobs VALUES (?,?)", (jobid, json.dumps(job)))
    return submit_groups(s, job)


def retry(s, ident):
    with lock:
        with s.db() as c:
            row = c.execute("SELECT value FROM album_jobs WHERE id=?", (ident,)).fetchone()
        if not row:
            raise ValueError("Album request not found.")
        return submit_groups(s, json.loads(row[0]), reconcile=True)


def request_destination(s, ident):
    with s.db() as c:
        jobs = [json.loads(r[0]) for r in c.execute("SELECT value FROM album_jobs")]
    return next(
        (x["destination"] for job in jobs for x in job["files"] if x["requestId"] == ident),
        None,
    )


def replace_request(s, old_id, new_id, record=None):
    with lock:
        with s.db() as c:
            c.execute("BEGIN IMMEDIATE")
            jobs = [json.loads(r[0]) for r in c.execute("SELECT value FROM album_jobs")]
            for job in jobs:
                changed = False
                for item in job["files"]:
                    if item["requestId"] == old_id:
                        item["requestId"] = new_id
                        changed = True
                        if record:
                            item.update(
                                file=record["file"],
                                status=record["status"],
                                batchId=record.get("batchId"),
                                destination=record.get("destination", item["destination"]),
                            )
                if changed:
                    c.execute(
                        "UPDATE album_jobs SET value=? WHERE id=?",
                        (json.dumps(job), job["id"]),
                    )
