"""Bounded, redacted JSON-lines diagnostics; no request bodies or configuration dumps."""

import contextvars, hashlib, io, json, logging, os, platform, re, threading, time, traceback, uuid, zipfile
from logging.handlers import RotatingFileHandler
from pathlib import Path

from build_meta import VERSION

request_id = contextvars.ContextVar("request_id", default="background")
lock = threading.RLock()
logger = logging.getLogger("resonance.diagnostics")
logger.setLevel(logging.INFO)
logger.propagate = False
log_dir = None
secret_supplier = lambda: []


def configure(data, secrets=None):
    global log_dir, secret_supplier
    target = Path(data) / "logs"
    with lock:
        if secrets is not None:
            secret_supplier = secrets
        if log_dir == target and logger.handlers:
            return
        for h in list(logger.handlers):
            h.close()
            logger.removeHandler(h)
        target.mkdir(parents=True, exist_ok=True)
        log_dir = target
        h = RotatingFileHandler(
            target / "resonance.log",
            maxBytes=2_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        h.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(h)
        try:
            os.chmod(target / "resonance.log", 0o600)
        except OSError:
            pass


def close():
    """Flush and release log handles before shutting down or removing a data directory."""
    global log_dir
    with lock:
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)
        log_dir = None


def redact(value):
    text = str(value)
    try:
        for secret in secret_supplier():
            if secret and len(str(secret)) >= 4:
                text = text.replace(str(secret), "[REDACTED]")
    except Exception:
        pass
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9_.\-]+", r"\1[REDACTED]", text)
    text = re.sub(
        r'(?i)(["\']?(?:password|api[_-]?key|authorization|secret|token|key)["\']?\s*[:=]\s*)(?:"[^"]*"|\'[^\']*\'|[^\s,;}]+)',
        r"\1[REDACTED]",
        text,
    )
    text = re.sub(
        r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b",
        "[REDACTED TOKEN]",
        text,
    )
    text = re.sub(r'\b[A-Za-z]:[\\/][^\r\n"<>]*', "[LOCAL PATH]", text)
    text = re.sub(r'/(?:workspace|home|Users)/[^\r\n"<>]*', "[LOCAL PATH]", text)
    text = re.sub(r"(https?://[^\s?]+)\?[^\s]*", r"\1?[QUERY OMITTED]", text)
    text = re.sub(r"\b[a-fA-F0-9]{32,}\b", "[REDACTED ID]", text)
    return text[:4000]


def endpoint(path):
    p = str(path).split("?", 1)[0]
    p = re.sub(r"(^|/)(users|conversations)/[^/]+", r"\1\2/{user}", p)
    p = re.sub(
        r"(transfers/(?:uploads|downloads))/[^/]+(?:/[^/]+)?",
        r"\1/{user}/{transfer}",
        p,
    )
    p = re.sub(r"(searches)/[a-fA-F0-9-]{36}", r"\1/{search}", p)
    p = re.sub(r"(artist|release-group)/[a-fA-F0-9-]{36}", r"\1/{mbid}", p)
    return redact(p)


def event(name, level="INFO", **fields):
    record = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "level": level,
        "event": name,
        "requestId": request_id.get(),
    }
    for k, v in fields.items():
        record[k] = redact(v) if isinstance(v, str) else v
    try:
        with lock:
            if logger.handlers:
                logger.log(
                    getattr(logging, level, logging.INFO),
                    json.dumps(record, ensure_ascii=False),
                )
    except OSError:
        pass


def error(exc, **fields):
    frames = [
        {"file": Path(f.filename).name, "line": f.lineno, "function": f.name}
        for f in traceback.extract_tb(exc.__traceback__)
    ][-12:]
    event(
        "exception",
        "ERROR",
        errorType=type(exc).__name__,
        message=redact(exc),
        frames=frames,
        **fields,
    )


def begin(method, path):
    rid = uuid.uuid4().hex[:12]
    request_id.set(rid)
    event("request", method=method, endpoint=endpoint(path))
    return rid


def manifest(root):
    hashes = {}
    files = list(Path(root).glob("*.py")) + list((Path(root) / "web").glob("*.js"))
    for f in sorted(str(p.relative_to(root)) for p in files):
        p = Path(root) / f
        hashes[f] = hashlib.sha256(p.read_bytes()).hexdigest()[:12] if p.is_file() else "MISSING"
    return {
        "application": "Resonance",
        "version": VERSION,
        "python": platform.python_version(),
        "os": platform.system(),
        "osRelease": platform.release(),
        "architecture": platform.machine(),
        "fileHashes": hashes,
        "capabilities": ["browse", "discovery-consent", "diagnostics", "redacted-logs"],
        "privacy": "No configuration, credentials, database, library, chat messages or request bodies are included. Inspect the report before sharing.",
    }


def report(root, browser_errors=None):
    memory = io.BytesIO()
    with lock:
        for h in logger.handlers:
            h.flush()
        with zipfile.ZipFile(memory, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("system.json", json.dumps(manifest(root), indent=2))
            if browser_errors is not None:
                allowed = {
                    "time",
                    "message",
                    "frontendVersion",
                    "page",
                    "method",
                    "endpoint",
                    "status",
                    "requestId",
                    "count",
                    "source",
                    "line",
                }
                cleaned = [
                    {
                        k: redact(v) if isinstance(v, str) else v
                        for k, v in row.items()
                        if k in allowed and isinstance(v, (str, int, float, bool, type(None)))
                    }
                    for row in browser_errors[:200]
                    if isinstance(row, dict)
                ]
                z.writestr("browser-errors.json", json.dumps(cleaned, indent=2))
            if log_dir:
                for p in sorted(log_dir.glob("resonance.log*")):
                    if p.is_file():
                        # Redact again in case a credential changed since an old log was written.
                        lines = [
                            redact(line)
                            for line in p.read_text(encoding="utf-8", errors="replace").splitlines()
                        ]
                        z.writestr("logs/" + p.name, "\n".join(lines) + "\n")
    return memory.getvalue()
