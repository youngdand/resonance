"""One bounded, consent-aware request policy for all discovery suppliers."""

from concurrent.futures import Future
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import urlsplit
import threading, time

HOSTS = {
    "www.allmusic.com",
    "www.officialcharts.com",
    "itunes.apple.com",
    "api.deezer.com",
    "coverartarchive.org",
    "musicbrainz.org",
    "api.listenbrainz.org",
    "pitchfork.com",
    "www.nme.com",
    "www.theguardian.com",
    "www.indieisnotagenre.com",
    "www.rollingstone.com",
    "www.nocleansinging.com",
    "www.silentradio.co.uk",
    "www.clashmusic.com",
    "thequietus.com",
}
lock = threading.RLock()
slots = threading.BoundedSemaphore(4)
hosts = {}
last = {}
inflight = {}
cooldowns = {}


def valid(url, allowed):
    u = urlsplit(url)
    return (
        u.scheme == "https"
        and not u.username
        and not u.password
        and u.port in (None, 443)
        and u.hostname in allowed
    )


def read(
    s,
    url,
    accept="application/json,text/html,application/rss+xml",
    limit=3_000_000,
    timeout=8,
    cancelled=None,
):
    host = urlsplit(url).hostname
    if host not in HOSTS or not valid(url, HOSTS):
        raise ValueError("Unsupported supplier URL.")

    def consent():
        if not s.settings(True).get("discoveryOnline", False) or cancelled and cancelled():
            raise ValueError("Online discovery stopped.")

    consent()
    key = (url, accept, limit)
    with lock:
        pending = inflight.get(key)
        if pending:
            leader = False
        else:
            pending = Future()
            inflight[key] = pending
            leader = True
        host_lock = hosts.setdefault(host, threading.Lock())
    if not leader:
        value = pending.result(timeout=timeout + 20)
        consent()
        return value
    try:
        with host_lock, slots:
            consent()
            if cooldowns.get(host, 0) > time.time():
                raise ValueError("Supplier is cooling down; cached information remains available.")
            remaining = (
                3.1 if host == "itunes.apple.com" else 1.1 if host == "musicbrainz.org" else 0.25
            ) - (time.monotonic() - last.get(host, 0))
            if remaining > 0:
                time.sleep(remaining)
            consent()

            class Redirect(HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    consent()
                    target = urlsplit(newurl).hostname or ""
                    allowed = {host}
                    if host == "coverartarchive.org" and (
                        target == "archive.org" or target.endswith(".archive.org")
                    ):
                        allowed.add(target)
                    if not valid(newurl, allowed):
                        raise ValueError("Unapproved supplier redirect.")
                    return super().redirect_request(req, fp, code, msg, headers, newurl)

            try:
                with build_opener(Redirect()).open(
                    Request(
                        url,
                        headers={
                            "User-Agent": "Resonance/"
                            + s.diag.VERSION
                            + " (personal desktop music discovery)",
                            "Accept": accept,
                        },
                    ),
                    timeout=timeout,
                ) as response:
                    raw = response.read(limit + 1)
                if len(raw) > limit:
                    raise ValueError("Supplier response exceeded its size limit.")
                pending.set_result(raw)
                return raw
            except Exception as exc:
                status = getattr(exc, "code", None)
                if status in (429, 503):
                    value = (getattr(exc, "headers", None) or {}).get("Retry-After", "60")
                    try:
                        delay = min(3600, max(60, float(value)))
                    except (ValueError, TypeError):
                        delay = 60
                    cooldowns[host] = time.time() + delay
                raise
            finally:
                last[host] = time.monotonic()
    except BaseException as exc:
        pending.set_exception(exc)
        raise
    finally:
        with lock:
            inflight.pop(key, None)


application = None


def urlopen(req, timeout=8):
    """urllib-compatible, bounded response facade for existing parser adapters."""
    import io

    url = req.full_url if hasattr(req, "full_url") else str(req)
    accept = req.get_header("Accept") if hasattr(req, "get_header") else None
    raw = read(
        application,
        url,
        accept=accept or "application/json,text/html,application/rss+xml",
        timeout=timeout,
    )

    class Response(io.BytesIO):
        def geturl(self):
            return url

    return Response(raw)
