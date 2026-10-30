"""Resonance: local Soulseek workspace. Python 3.10+, optional mutagen."""

from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path, PureWindowsPath
from urllib.request import Request, urlopen
from urllib.parse import urlsplit, quote, parse_qs
from urllib.error import HTTPError, URLError
import argparse, json, sqlite3, threading, time, uuid, re, unicodedata, os, mimetypes, webbrowser, secrets, sys
from features import get_route, post_route
import discovery
import new_releases
import diagnostics as diag
import library_sync
import album_jobs
import realtime
import transfer_progress
import storage, identity, library_index
from transfer_state import classify, succeeded

ROOT = Path(__file__).parent
DATA = Path(os.environ.get("RESONANCE_DATA_DIR", str(ROOT / "data")))
AUDIO = {
    ".flac",
    ".mp3",
    ".m4a",
    ".aac",
    ".ogg",
    ".opus",
    ".wav",
    ".aiff",
    ".aif",
    ".alac",
    ".wma",
    ".ape",
}
TOKEN = secrets.token_urlsafe(32)
scan_lock = threading.Lock()
scan_state = {"running": False, "count": 0, "error": None}


def db():
    return storage.connect(DATA / "resonance.db")


def init():
    DATA.mkdir(parents=True, exist_ok=True)
    storage.backup_before_migration(DATA)
    with db() as c:
        c.executescript(
            """PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS tracks (path TEXT PRIMARY KEY, root TEXT, artist TEXT, album TEXT, title TEXT, duration REAL, format TEXT, size INTEGER);
        CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS searches (id TEXT PRIMARY KEY, query TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS album_jobs (id TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS track_metadata (path TEXT PRIMARY KEY, size TEXT, mtime TEXT, value TEXT);
        """
        )
    storage.migrate(sys.modules[__name__])
    discovery.init(sys.modules[__name__])
    for module in (
        new_releases,
        new_releases.release_details,
        new_releases.review_sources,
        new_releases.release_artwork,
    ):
        module.init(sys.modules[__name__])
    identity.migrate(sys.modules[__name__])
    diag.configure(DATA, lambda: [settings(True).get("key", ""), TOKEN])
    import config_journal, supplier_http

    supplier_http.application = sys.modules[__name__]
    config_journal.recover(sys.modules[__name__])


def settings(private=False):
    with db() as c:
        r = c.execute("SELECT value FROM settings WHERE id=1").fetchone()
    s = {
        "url": "http://127.0.0.1:5030",
        "key": "",
        "roots": [],
        "formats": [
            "flac",
            "mp3",
            "m4a",
            "wav",
            "aiff",
            "aif",
            "ogg",
            "opus",
            "aac",
            "ape",
            "wma",
            "alac",
        ],
        "minBitrate": 0,
        "hideOwned": False,
        "blocked": [],
        "slskdConfig": "",
        "librarySource": "slskd",
    }
    if r:
        value = json.loads(r[0])
        if not isinstance(value, dict):
            raise ValueError("Saved settings are invalid. Restore a private backup.")
        s.update(value)
    if not private:
        s["hasKey"] = bool(s.pop("key", ""))
    return s


def norm(s):
    return identity.normalize(s)


def filename_title(s):
    stem = PureWindowsPath(s.replace("/", "\\")).stem
    return re.sub(r"^\s*\d{1,3}[\s.\-_]+", "", stem).strip()


def owned(f, tracks=None):
    if tracks is None:
        with db() as c:
            tracks = [dict(r) for r in c.execute("SELECT * FROM tracks")]
    title = norm(filename_title(f["filename"]))
    duration = f.get("duration", 0)
    hits = (
        tracks.get(title, [])
        if isinstance(tracks, dict)
        else [t for t in tracks if norm(t["title"]) == title]
    )
    if not hits:
        return "new"
    # Remote filenames are not reliable artist tags. Be conservative.
    context = " " + norm(f["filename"]) + " "
    for t in hits:
        if (
            norm(t["artist"])
            and " " + norm(t["artist"]) + " " in context
            and duration
            and t["duration"]
            and abs(duration - t["duration"]) <= 2
        ):
            return "owned"
    return "possible"


class UpstreamError(ValueError):
    def __init__(self, message, status=None, code=None, retryable=False):
        super().__init__(message)
        self.status = status
        self.code = code
        self.retryable = retryable


def slsk(path, method="GET", body=None):
    s = settings(True)
    if not s["key"]:
        raise ValueError("Connect slskd in Settings first, or use Demo mode.")
    req = Request(
        s["url"].rstrip("/") + "/api/v0/" + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"X-API-Key": s["key"], "Content-Type": "application/json"},
    )
    try:
        with urlopen(
            req,
            timeout=(
                120
                if path == "shares/contents"
                or path.startswith("users/")
                and path.endswith("/browse")
                else 35
            ),
        ) as r:
            data = r.read()
            if method == "POST" and path.startswith("conversations/") and r.status != 201:
                raise ValueError(
                    "The message was not accepted by slskd. Check whether the recipient is blocked."
                )
            return json.loads(data) if data else {}
    except HTTPError as e:
        raw = e.read(6000).decode("utf-8", errors="replace")
        detail = (
            "[message body omitted]"
            if path.startswith("conversations/")
            else diag.redact(raw)[:2500]
        )
        diag.event(
            "upstream-http-error",
            "ERROR",
            service="slskd",
            method=method,
            endpoint=diag.endpoint(path),
            status=e.code,
            response=detail,
        )
        try:
            problem = json.loads(raw)
        except (ValueError, TypeError):
            problem = {}
        known = {
            "user_offline",
            "browse_timeout",
            "peer_unreachable",
            "soulseek_disconnected",
            "library_not_ready",
            "library_changed",
            "library_metadata_missing",
        }
        code = problem.get("code") if isinstance(problem, dict) else None
        message = (
            diag.redact(problem.get("message", ""))
            if code in known
            else f"slskd returned HTTP {e.code} while calling {diag.endpoint(path)}. Details were saved in the diagnostic log."
        )
        raise UpstreamError(
            message,
            status=e.code,
            code=code,
            retryable=(bool(problem.get("retryable")) if isinstance(problem, dict) else False),
        ) from None
    except (URLError, TimeoutError) as e:
        diag.event(
            "upstream-connection-error",
            "ERROR",
            service="slskd",
            method=method,
            endpoint=diag.endpoint(path),
            errorType=type(e).__name__,
        )
        raise UpstreamError(
            "Cannot reach slskd. Check that it is running and the address is correct.",
            code="slskd_unreachable",
            retryable=True,
        ) from None


def attr(file, name, attribute):
    if file.get(name) is not None:
        return file[name]
    for a in file.get("attributes", []) or []:
        if a.get("type") in (attribute, str(attribute), name[0].upper() + name[1:]):
            return a.get("value", 0)
    return 0


def flatten(responses):
    rows = []
    if isinstance(responses, dict):
        responses = responses.get("responses", [])
    for resp in responses or []:
        for f in resp.get("files", []):
            rows.append(
                {
                    "username": resp.get("username", ""),
                    "filename": f.get("filename", ""),
                    "size": f.get("size", 0),
                    "bitrate": attr(f, "bitRate", 0),
                    "duration": attr(f, "length", 1),
                    "sampleRate": attr(f, "sampleRate", 4),
                    "bitDepth": attr(f, "bitDepth", 5),
                    "slots": resp.get("hasFreeUploadSlot", False),
                    "queue": resp.get("queueLength", 0),
                    "speed": resp.get("uploadSpeed", 0),
                }
            )
    return rows


def annotate(rows):
    index = library_index.get(sys.modules[__name__])["titles"]
    with db() as c:
        reqs = [json.loads(r[0]) for r in c.execute("SELECT value FROM requests")]
    seen = {(r["file"]["username"], r["file"]["filename"]): r["status"] for r in reqs}
    for f in rows:
        f["ownership"] = owned(f, index)
        f["localStatus"] = seen.get((f["username"], f["filename"]))
    return rows


def scan(roots):
    import folder_scan

    folder_scan.run(sys.modules[__name__], roots)


def save_request(r):
    with db() as c:
        c.execute("INSERT OR REPLACE INTO requests VALUES (?,?)", (r["id"], json.dumps(r)))


def queue_file(file, query, replaces=None, album_root=None):
    import downloads

    return downloads.queue(sys.modules[__name__], file, query, replaces, album_root)


def sync_downloads(remote=None):
    if remote is None:
        remote = slsk("transfers/downloads")
    lookup = {}
    for user in remote if isinstance(remote, list) else []:
        for directory in user.get("directories", []):
            for file in directory.get("files", []):
                lookup[(user["username"], file["filename"])] = file
    # One transaction per snapshot; retain concurrent cancel/archive/recovery changes.
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        rs = [json.loads(r[0]) for r in c.execute("SELECT value FROM requests")]
        for r in rs:
            f = lookup.get((r["file"]["username"], r["file"]["filename"]))
            if (
                not f
                and (r.get("transferId") or time.time() - r.get("created", time.time()) > 30)
                and classify(r["status"]) in ("active", "queued")
            ):
                r["status"] = "Missing, Unconfirmed"
                c.execute("UPDATE requests SET value=? WHERE id=?", (json.dumps(r), r["id"]))
            if f and r["status"] not in ("Replaced", "Cancelled"):
                changes = {
                    "status": f.get("state", "Unknown"),
                    "transferId": f.get("id"),
                    "bytesTransferred": f.get("bytesTransferred", 0),
                    "averageSpeed": f.get("averageSpeed", 0),
                    "currentSpeed": f.get("currentSpeed", f.get("averageSpeed", 0)),
                }
                if any(r.get(k) != v for k, v in changes.items()):
                    r.update(changes)
                    c.execute(
                        "UPDATE requests SET value=? WHERE id=?",
                        (json.dumps(r), r["id"]),
                    )
    return rs


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def handle(self):
        try:
            super().handle()
        except realtime.CLIENT_DISCONNECTS:
            self.close_connection = True

    def finish(self):
        try:
            super().finish()
        except realtime.CLIENT_DISCONNECTS:
            pass

    def api_error(self, exc):
        if isinstance(exc, realtime.CLIENT_DISCONNECTS):
            self.close_connection = True
            return
        diag.error(exc, method=self.command, endpoint=diag.endpoint(self.path))
        self.send_json(
            {
                "error": diag.redact(exc),
                "code": getattr(exc, "code", None),
                "retryable": getattr(exc, "retryable", False),
                "requestId": diag.request_id.get(),
                "version": diag.VERSION,
            },
            (
                502
                if isinstance(exc, UpstreamError)
                else 400 if isinstance(exc, (ValueError, KeyError, TypeError)) else 500
            ),
        )

    def send_json(self, value, status=200):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def authorized(self, mutate=False):
        host = self.headers.get("Host", "")
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            self.send_json({"error": "Local access only"}, 403)
            return False
        if host not in (
            f"127.0.0.1:{self.server.server_port}",
            f"localhost:{self.server.server_port}",
        ):
            self.send_json({"error": "Local access only"}, 403)
            return False
        if mutate and not secrets.compare_digest(self.headers.get("X-Resonance-Token", ""), TOKEN):
            self.send_json({"error": "Reload this page before making changes."}, 403)
            return False
        return True

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def do_GET(self):
        diag.begin("GET", self.path)
        if not self.authorized():
            return
        u = urlsplit(self.path)
        q = parse_qs(u.query)
        try:
            if new_releases.get_route(self, u.path, q, sys.modules[__name__]):
                return
            if discovery.get_route(self, u.path, q, sys.modules[__name__]):
                return
            if get_route(self, u.path, q, sys.modules[__name__]):
                return
            if u.path == "/api/diagnostics":
                self.send_json(diag.manifest(ROOT))
                return
            if u.path == "/api/diagnostics/download":
                body = diag.report(ROOT)
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header(
                    "Content-Disposition",
                    "attachment; filename=Resonance-Diagnostics.zip",
                )
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if u.path == "/api/state":
                with db() as c:
                    count = c.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
                    rs = [json.loads(r[0]) for r in c.execute("SELECT value FROM requests")]
                    history = [
                        dict(r)
                        for r in c.execute("SELECT * FROM searches ORDER BY created DESC LIMIT 15")
                    ]
                self.send_json(
                    {
                        "settings": settings(),
                        "tracks": count,
                        "scan": scan_state,
                        "requests": rs,
                        "searches": history,
                        "token": TOKEN,
                        "version": diag.VERSION,
                        "capabilities": [
                            "discovery",
                            "diagnostics",
                            "share-library",
                            "clear-completed",
                        ],
                    }
                )
                return
            if u.path == "/api/results":
                sid = q.get("id", [""])[0]
                result = slsk("searches/" + quote(sid, safe="") + "?includeResponses=true")
                responses = result.get("responses")
                if responses is None:
                    responses = slsk("searches/" + quote(sid, safe="") + "/responses")
                self.send_json(
                    {
                        "files": annotate(flatten(responses)),
                        "state": result.get("state", ""),
                        "isComplete": result.get("isComplete", False),
                    }
                )
                return
            if u.path == "/api/events":
                realtime.stream(self, sys.modules[__name__], q.get("transfers", [""])[0])
                return
            if u.path == "/api/transfer-progress":
                self.send_json(
                    transfer_progress.snapshot(sys.modules[__name__], q.get("direction", [""])[0])
                )
                return
            if u.path == "/api/album-jobs":
                self.send_json(album_jobs.list_jobs(sys.modules[__name__]))
                return
            if u.path == "/api/library":
                term = q.get("q", [""])[0]
                offset = max(0, int(q.get("offset", ["0"])[0]))
                limit = min(250, max(1, int(q.get("limit", ["100"])[0])))
                where = " WHERE artist LIKE ? OR album LIKE ? OR title LIKE ?"
                params = tuple(["%" + term + "%"] * 3)
                with db() as c:
                    c.execute("BEGIN")
                    total = c.execute("SELECT COUNT(*) FROM tracks" + where, params).fetchone()[0]
                    albums = c.execute(
                        "SELECT COUNT(*) FROM (SELECT artist,album FROM tracks"
                        + where
                        + " GROUP BY artist,album)",
                        params,
                    ).fetchone()[0]
                    rows = [
                        dict(r)
                        for r in c.execute(
                            "SELECT * FROM tracks"
                            + where
                            + " ORDER BY artist,album,title,path LIMIT ? OFFSET ?",
                            (*params, limit, offset),
                        )
                    ]
                self.send_json(
                    {
                        "items": rows,
                        "total": total,
                        "albums": albums,
                        "offset": offset,
                        "limit": limit,
                    }
                )
                return
            if u.path == "/api/browse":
                username = q.get("username", [""])[0].strip()
                if not username:
                    raise ValueError("Enter a username.")
                result = slsk("users/" + quote(username, safe="") + "/browse")
                dirs = result if isinstance(result, list) else result.get("directories", [])
                rows = []
                for d in dirs:
                    for f in d.get("files", []):
                        f = dict(f)
                        filename = f.get("filename", "")
                        directory = d.get("name", d.get("directory", ""))
                        if directory and not filename.startswith(directory):
                            f["filename"] = directory.rstrip("\\/") + "\\" + filename
                        rows.extend(flatten([{"username": username, "files": [f]}]))
                self.send_json({"files": annotate(rows), "username": username})
                return
            if u.path == "/api/ping":
                r = slsk("application")
                self.send_json({"ok": True, "application": r})
                return
            if u.path == "/api/sync":
                self.send_json(sync_downloads())
                return
            if u.path == "/build.js":
                body = (
                    "window.RESONANCE_BUILD=" + json.dumps({"version": diag.VERSION}) + ";"
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            file = ROOT / "web" / ("index.html" if u.path == "/" else u.path.lstrip("/"))
            if not file.resolve().is_relative_to((ROOT / "web").resolve()) or not file.is_file():
                if u.path.startswith("/api/"):
                    diag.event(
                        "route-not-found",
                        "ERROR",
                        endpoint=diag.endpoint(self.path),
                        method="GET",
                    )
                    self.send_json(
                        {
                            "error": "This local API route is not available. Check that all update files were copied and restart the Resonance console.",
                            "requestId": diag.request_id.get(),
                            "version": diag.VERSION,
                        },
                        404,
                    )
                else:
                    self.send_error(404)
                return
            body = file.read_bytes()
            self.send_response(200)
            self.send_header(
                "Content-Type",
                mimetypes.guess_type(str(file))[0] or "application/octet-stream",
            )
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.api_error(e)

    def do_POST(self):
        diag.begin("POST", self.path)
        if not self.authorized(True):
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2_000_000:
                raise ValueError("Request body must be between 1 and 2,000,000 bytes.")
            b = json.loads(self.rfile.read(length))
            path = urlsplit(self.path).path
            if not isinstance(b, dict):
                raise ValueError("Request must contain a JSON object.")
            if path == "/api/diagnostics/download":
                errors = b.get("errors", [])
                if not isinstance(errors, list):
                    raise ValueError("Invalid browser error history.")
                body = diag.report(ROOT, errors)
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header(
                    "Content-Disposition",
                    "attachment; filename=Resonance-Diagnostics.zip",
                )
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/client-error":
                diag.event(
                    "browser-error",
                    "ERROR",
                    message=diag.redact(b.get("message", ""))[:2000],
                    page=diag.endpoint(b.get("page", "")),
                    source=diag.endpoint(b.get("source", "")),
                    line=str(b.get("line", ""))[:20],
                )
                self.send_json({"ok": True})
                return
            if new_releases.post_route(self, path, b, sys.modules[__name__]):
                return
            if discovery.post_route(self, path, b, sys.modules[__name__]):
                return
            if post_route(self, path, b, sys.modules[__name__]):
                return
            if path == "/api/settings":
                s = settings(True)
                for k in (
                    "url",
                    "roots",
                    "formats",
                    "minBitrate",
                    "hideOwned",
                    "blocked",
                    "slskdConfig",
                    "librarySource",
                ):
                    if k in b:
                        s[k] = b[k]
                if b.get("key"):
                    s["key"] = b["key"]
                u = urlsplit(s["url"])
                if (
                    u.scheme not in ("http", "https")
                    or u.hostname not in ("localhost", "127.0.0.1", "::1")
                    or u.username
                    or u.password
                    or u.query
                    or u.fragment
                ):
                    raise ValueError("Use a local slskd address, such as http://127.0.0.1:5030")
                if not isinstance(s["roots"], list) or not all(
                    isinstance(r, str) for r in s["roots"]
                ):
                    raise ValueError("Folders must be a list of paths.")
                if not isinstance(s["formats"], list) or not all(
                    isinstance(f, str) for f in s["formats"]
                ):
                    raise ValueError("Formats must be a list.")
                if s["librarySource"] not in ("slskd", "folders"):
                    raise ValueError("Choose a valid collection source.")
                if not isinstance(s.get("blocked"), list) or not all(
                    isinstance(x, str) and len(x) <= 200 for x in s["blocked"]
                ):
                    raise ValueError("Hidden users must be a list of usernames.")
                if (
                    isinstance(s.get("minBitrate"), bool)
                    or not isinstance(s.get("minBitrate"), (int, float))
                    or not 0 <= s["minBitrate"] <= 100000
                ):
                    raise ValueError("Minimum bitrate must be a nonnegative number.")
                if not isinstance(s.get("hideOwned"), bool) or not isinstance(
                    s.get("slskdConfig"), str
                ):
                    raise ValueError("Invalid collection settings.")
                storage.settings_patch(sys.modules[__name__], {k: s[k] for k in b if k in s})
                self.send_json(settings())
                return
            if path == "/api/scan":
                if settings(True)["librarySource"] == "slskd":
                    self.send_json(library_sync.start(sys.modules[__name__], refresh=True))
                    return
                roots = settings(True)["roots"]
                if not roots:
                    raise ValueError("Add a music folder in Settings first.")
                if not scan_lock.acquire(False):
                    raise ValueError("A scan is already running.")
                scan_state.update(running=True, count=0, error=None)
                threading.Thread(target=scan, args=(roots,), daemon=True).start()
                self.send_json(scan_state)
                return
            if path == "/api/queue-album":
                self.send_json(album_jobs.enqueue(sys.modules[__name__], b))
                return
            if path == "/api/library-sync":
                if settings(True)["librarySource"] != "slskd":
                    raise ValueError("Choose slskd shared library in Settings first.")
                self.send_json(library_sync.start(sys.modules[__name__]))
                return
            if path == "/api/search":
                query = str(b.get("query", "")).strip()
                if not query or len(query) > 300:
                    raise ValueError("Enter a search of 1–300 characters.")
                sid = str(uuid.uuid4())
                slsk("searches", "POST", {"id": sid, "searchText": query})
                with db() as c:
                    c.execute("INSERT INTO searches VALUES (?,?,?)", (sid, query, time.time()))
                self.send_json({"id": sid, "query": query})
                return
            if path == "/api/reconcile-album":
                self.send_json(album_jobs.retry(sys.modules[__name__], str(b.get("id", ""))))
                return
            if path == "/api/reconcile":
                import downloads

                self.send_json(downloads.retry(sys.modules[__name__], str(b.get("id", ""))))
                return
            if path == "/api/queue":
                self.send_json(
                    queue_file(
                        b["file"],
                        str(b.get("query", "")),
                        b.get("replaces"),
                        b.get("albumRoot"),
                    )
                )
                return
            if path == "/api/cancel":
                with db() as c:
                    row = c.execute("SELECT value FROM requests WHERE id=?", (b["id"],)).fetchone()
                if not row:
                    raise ValueError("Request not found")
                r = json.loads(row[0])
                if not r.get("transferId"):
                    import downloads

                    r = downloads.retry(sys.modules[__name__], r["id"])
                    if not r.get("transferId"):
                        raise ValueError(
                            "Acceptance is uncertain. Reconcile again when the engine is available; do not assume cancellation."
                        )
                slsk(
                    "transfers/downloads/"
                    + quote(r["file"]["username"], safe="")
                    + "/"
                    + quote(str(r["transferId"]), safe=""),
                    "DELETE",
                )
                r["status"] = "Cancelled"
                save_request(r)
                self.send_json(r)
                return
            diag.event(
                "route-not-found",
                "ERROR",
                endpoint=diag.endpoint(self.path),
                method="POST",
            )
            self.send_json(
                {
                    "error": "This local API route is not available. Restart the Resonance console after copying all update files.",
                    "requestId": diag.request_id.get(),
                    "version": diag.VERSION,
                },
                404,
            )
        except Exception as e:
            self.api_error(e)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    a = p.parse_args()
    init()
    server = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    diag.event("startup", version=diag.VERSION, port=a.port, python=sys.version.split()[0])
    print(
        f"Resonance is running at http://127.0.0.1:{a.port}\nKeep this window open. Press Ctrl+C to stop."
    )
    if not a.no_browser:
        webbrowser.open(f"http://127.0.0.1:{a.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
