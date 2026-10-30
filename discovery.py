"""Opt-in library-seeded discovery. No external request is made without consent."""

import json, time, threading, uuid, re, random, math
import diagnostics as diag
from urllib.request import Request
from supplier_http import urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from email.utils import parsedate_to_datetime
from datetime import timezone

state_lock = threading.RLock()
fetch_lock = threading.Lock()
last_fetch = {}
service_cooldowns = {}
job = {
    "running": False,
    "progress": "",
    "errors": [],
    "candidates": [],
    "updated": 0,
    "cancel": False,
    "warnings": [],
    "retryAt": 0,
}
MB = "https://musicbrainz.org/ws/2/"
LB = "https://api.listenbrainz.org/1/lb-radio/artist/"


def init(s):
    import storage

    storage.ensure_schema(
        s,
        "discovery",
        """CREATE TABLE IF NOT EXISTS discovery_cache (key TEXT PRIMARY KEY, value TEXT, updated REAL);
    CREATE TABLE IF NOT EXISTS discovery_items (id TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS discovery_feedback (id TEXT PRIMARY KEY, status TEXT);
    CREATE TABLE IF NOT EXISTS discovery_matches (artist TEXT PRIMARY KEY, mbid TEXT, name TEXT);""",
    )


def profile(s):
    import library_index

    return library_index.get(s)["profile"]


class CatalogueUnavailable(ValueError):
    def __init__(self, host, retry_at=0):
        self.host = host
        self.retry_at = retry_at
        super().__init__(
            ("MusicBrainz" if host == "musicbrainz.org" else "ListenBrainz")
            + " is temporarily unavailable. Cached discoveries are still available. Please retry after the cooldown."
        )


def retry_delay(value, default):
    try:
        seconds = float(value)
        return max(default, seconds) if math.isfinite(seconds) else default
    except (TypeError, ValueError):
        try:
            date = parsedate_to_datetime(str(value))
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            return max(default, date.timestamp() - time.time())
        except (ValueError, TypeError, OverflowError):
            return default


def add_warning(message):
    with state_lock:
        warnings = job.setdefault("warnings", [])
        if message not in warnings:
            warnings.append(message)
        job["warnings"] = warnings[-12:]


def wait_for_retry(s, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if job.get("cancel") or not s.settings(True).get("discoveryOnline", False):
            raise ValueError("Discovery stopped.")
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(0.2, remaining))


def cached_json(s, url, max_age=7 * 86400):
    init(s)
    host = urlsplit(url).hostname
    if host not in ("musicbrainz.org", "api.listenbrainz.org"):
        raise ValueError("Unsupported discovery service.")
    name = "MusicBrainz" if host == "musicbrainz.org" else "ListenBrainz"

    def read_cache():
        with s.db() as c:
            return c.execute(
                "SELECT value,updated FROM discovery_cache WHERE key=?", (url,)
            ).fetchone()

    row = read_cache()
    if row and time.time() - row["updated"] < max_age:
        return json.loads(row["value"])

    def stale_cache():
        if row and time.time() - row["updated"] < 90 * 86400:
            add_warning(
                name
                + " is unavailable; using cached catalogue data from "
                + time.strftime("%d %b %Y", time.localtime(row["updated"]))
                + "."
            )
            return json.loads(row["value"])
        return None

    def unavailable(until):
        job["retryAt"] = max(job.get("retryAt", 0), until)
        stale = stale_cache()
        if stale is not None:
            return stale
        raise CatalogueUnavailable(host, until)

    if not s.settings(True).get("discoveryOnline", False):
        stale = stale_cache()
        if stale is not None:
            return stale
        raise ValueError("Online discovery is off. Enable it on the For You screen first.")
    if job.get("cancel"):
        raise ValueError("Discovery stopped.")
    if service_cooldowns.get(host, 0) > time.time():
        return unavailable(service_cooldowns[host])
    for attempt in range(3):
        if job.get("cancel") or not s.settings(True).get("discoveryOnline", False):
            raise ValueError("Discovery stopped.")
        delay = 0
        with fetch_lock:
            # Recheck after waiting for another caller, including its successful cache fill/cooldown.
            row = read_cache()
            if row and time.time() - row["updated"] < max_age:
                return json.loads(row["value"])
            if service_cooldowns.get(host, 0) > time.time():
                return unavailable(service_cooldowns[host])
            elapsed = time.monotonic() - last_fetch.get(host, 0)
            if elapsed < 1.1:
                wait_for_retry(s, 1.1 - elapsed)
            if job.get("cancel") or not s.settings(True).get("discoveryOnline", False):
                raise ValueError("Discovery stopped.")
            req = Request(
                url,
                headers={
                    "User-Agent": "Resonance/"
                    + diag.VERSION
                    + " (personal desktop music discovery)",
                    "Accept": "application/json",
                },
            )
            try:
                with urlopen(req, timeout=12) as response:
                    data = json.load(response)
                if not isinstance(data, (dict, list)):
                    raise ValueError("Invalid catalogue response")
            except HTTPError as e:
                diag.event(
                    "catalogue-http-error",
                    "WARNING",
                    service=host,
                    endpoint=diag.endpoint(urlsplit(url).path),
                    status=e.code,
                    attempt=attempt + 1,
                )
                if e.code not in (429, 500, 502, 503, 504):
                    e.close()
                    raise ValueError(
                        f"{name} returned HTTP {e.code}. Check the catalogue request in Diagnostics."
                    ) from None
                delay = retry_delay(
                    e.headers.get("Retry-After") if e.headers else None,
                    2 ** (attempt + 1),
                )
                e.close()
            except (URLError, TimeoutError, OSError, ValueError) as e:
                diag.event(
                    "catalogue-request-error",
                    "WARNING",
                    service=host,
                    errorType=type(e).__name__,
                    attempt=attempt + 1,
                )
                delay = 2 ** (attempt + 1)
            else:
                with s.db() as c:
                    c.execute(
                        "INSERT OR REPLACE INTO discovery_cache VALUES (?,?,?)",
                        (url, json.dumps(data), time.time()),
                    )
                service_cooldowns.pop(host, None)
                return data
            finally:
                last_fetch[host] = time.monotonic()
        # Do not block all other catalogue requests while backing off. Long Retry-After
        # values become a service cooldown; no request is sent before that expires.
        if attempt == 2 or delay > 30:
            until = time.time() + max(30, delay)
            service_cooldowns[host] = until
            return unavailable(until)
        with state_lock:
            job["progress"] = (
                f"{name} is busy. Retrying in {delay:.0f}s (attempt {attempt+2} of 3)…"
            )
        wait_for_retry(s, delay)


def mb(s, entity, params):
    return cached_json(s, MB + entity + "?" + urlencode({**params, "fmt": "json"}))


def literal(v):
    return '"' + re.sub(r'([+\-&|!(){}\[\]^"~*?:\\/])', r"\\\1", str(v)) + '"'


def valid_id(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid catalogue identifier.") from None


def resolve(s, name):
    with s.db() as c:
        r = c.execute(
            "SELECT mbid,name FROM discovery_matches WHERE artist=?", (s.norm(name),)
        ).fetchone()
    if r:
        return dict(r)
    candidates = mb(s, "artist/", {"query": "artist:" + literal(name), "limit": 5}).get(
        "artists", []
    )
    exact = [a for a in candidates if s.norm(a["name"]) == s.norm(name)]
    if len(exact) == 1:
        # Keep a confirmed exact identity so a catalogue search outage need not prevent ListenBrainz discovery.
        match = {"mbid": valid_id(exact[0]["id"]), "name": exact[0]["name"]}
        with s.db() as c:
            c.execute(
                "INSERT OR REPLACE INTO discovery_matches VALUES (?,?,?)",
                (s.norm(name), match["mbid"], match["name"]),
            )
        return match
    with state_lock:
        job["candidates"].append(
            {
                "artist": name,
                "choices": [
                    {
                        "mbid": a["id"],
                        "name": a["name"],
                        "detail": a.get("disambiguation", "") or a.get("type", ""),
                    }
                    for a in (exact or candidates)[:5]
                ],
            }
        )
    return None


def normal_album(s, v):
    # Ignore common edition suffixes only for duplicate hints; never infer complete ownership.
    return s.norm(
        re.sub(
            r"\s*[\[(](?:deluxe|expanded|remaster(?:ed)?|anniversary|special edition)[^\])]*[\])]",
            "",
            v,
            flags=re.I,
        )
    )


def ownership(s, artist, album=None, rows=None):
    if rows is None:
        import library_index

        index = library_index.get(s)
        a = s.norm(artist)
        if not a:
            return "new-artist" if album is None else "not-in-library"
        if album is None:
            return "artist-in-library" if a in index["artists"] else "new-artist"
        if (a, s.norm(album)) in index["exact"]:
            return "album-in-library"
        if (a, normal_album(s, album)) in index["loose"]:
            return "possible-album"
        return "not-in-library"
    exact = [r for r in rows if s.norm(r["artist"]) == s.norm(artist)]
    if album is None:
        return "artist-in-library" if exact else "new-artist"
    if any(s.norm(r["album"]) == s.norm(album) for r in exact):
        return "album-in-library"
    if any(normal_album(s, r["album"]) == normal_album(s, album) for r in exact):
        return "possible-album"
    return "not-in-library"


def add(s, item):
    item["id"] = item.get("id") or item["kind"] + ":" + item["mbid"]
    item["libraryStatus"] = ownership(s, item["artist"], item.get("album"))
    item["updated"] = time.time()
    import metadata_store

    metadata_store.save(s, item)


def album_items(s, aid, name, reason, kind="album"):
    data = mb(
        s,
        "release-group",
        {
            "artist": valid_id(aid),
            "type": "album",
            "release-group-status": "website-default",
            "limit": 100,
        },
    )
    # Show genuine studio-album candidates, rather than live releases and compilations.
    rows = [
        r
        for r in data.get("release-groups", [])
        if r.get("primary-type") == "Album" and not r.get("secondary-types")
    ]
    rows.sort(key=lambda r: (r.get("first-release-date") or "9999", r.get("title", "")))
    missing = [r for r in rows if ownership(s, name, r["title"]) not in ("album-in-library",)]
    for r in missing[:4]:
        add(
            s,
            {
                "kind": kind,
                "mbid": r["id"],
                "artist": name,
                "artistMbid": aid,
                "album": r["title"],
                "year": r.get("first-release-date", "")[:4],
                "source": "MusicBrainz catalogue",
                "reason": reason,
                "url": "https://musicbrainz.org/release-group/" + r["id"],
            },
        )


def similar_artists(s, aid, mode):
    data = cached_json(
        s,
        LB
        + valid_id(aid)
        + "?"
        + urlencode(
            {
                "mode": mode,
                "max_similar_artists": 8,
                "max_recordings_per_artist": 1,
                "pop_begin": 0,
                "pop_end": 100,
            }
        ),
    )
    artists = {}

    def walk(x):
        if isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, dict):
            mid = x.get("similar_artist_mbid")
            name = x.get("similar_artist_name")
            if mid and name and mid != aid:
                artists.setdefault(mid, {"mbid": mid, "name": name})
            for v in x.values():
                if isinstance(v, (dict, list)):
                    walk(v)

    walk(data)
    return list(artists.values())


def related_album_tags(s, aid, seed_album, seed_name):
    result = mb(
        s,
        "release-group/",
        {
            "query": "arid:" + valid_id(aid) + " AND releasegroup:" + literal(seed_album),
            "limit": 5,
        },
    )
    exact = [
        r
        for r in result.get("release-groups", [])
        if normal_album(s, r["title"]) == normal_album(s, seed_album)
    ]
    if len(exact) != 1:
        return
    rg = mb(s, "release-group/" + valid_id(exact[0]["id"]), {"inc": "tags"})
    tags = [
        t["name"]
        for t in sorted(rg.get("tags", []), key=lambda t: -t.get("count", 0))
        if t.get("count", 0) > 0
    ][:2]
    if not tags:
        return
    query = (
        "("
        + " OR ".join("tag:" + literal(t) for t in tags)
        + ") AND primarytype:album AND -arid:"
        + valid_id(aid)
    )
    related = mb(s, "release-group/", {"query": query, "limit": 12})
    for r in related.get("release-groups", []):
        if r.get("secondary-types"):
            continue
        credit = [a for a in r.get("artist-credit", []) if isinstance(a, dict) and a.get("artist")]
        if not credit:
            continue
        a = credit[0]["artist"]
        add(
            s,
            {
                "kind": "tag-album",
                "mbid": r["id"],
                "artist": a["name"],
                "artistMbid": a["id"],
                "album": r["title"],
                "year": r.get("first-release-date", "")[:4],
                "source": "MusicBrainz shared tags",
                "reason": f'Shares {", ".join(tags)} tags with {seed_name} — {seed_album}',
                "url": "https://musicbrainz.org/release-group/" + r["id"],
            },
        )


def worker(s, seeds, mode, seed_album):
    try:
        for name in seeds:
            if job.get("cancel") or not s.settings(True).get("discoveryOnline", False):
                break
            with state_lock:
                job["progress"] = "Matching " + name + " to the catalogue…"
            try:
                a = resolve(s, name)
                if not a:
                    continue
                aid = valid_id(a["mbid"])
                artist = a["name"]
                with state_lock:
                    job["progress"] = "Finding albums by " + artist + "…"
                try:
                    album_items(
                        s,
                        aid,
                        artist,
                        "More studio albums by " + name + " from your library",
                        "missing-album",
                    )
                except ValueError as e:
                    if job.get("cancel") or not s.settings(True).get("discoveryOnline", False):
                        break
                    diag.error(e, operation="discovery-worker")
                    with state_lock:
                        if str(e) not in job["errors"]:
                            job["errors"].append(str(e))
                if seed_album:
                    try:
                        related_album_tags(s, aid, seed_album, name)
                    except ValueError as e:
                        if job.get("cancel") or not s.settings(True).get("discoveryOnline", False):
                            break
                        diag.error(e, operation="discovery-worker")
                        with state_lock:
                            if str(e) not in job["errors"]:
                                job["errors"].append(str(e))
                with state_lock:
                    job["progress"] = "Finding artists related to " + artist + "…"
                similar = similar_artists(s, aid, mode)
                if not similar:
                    with state_lock:
                        job["errors"].append(
                            "No related-artist data for "
                            + artist
                            + ". Catalogue gaps are still shown."
                        )
                for i, x in enumerate(similar[:6]):
                    if job.get("cancel"):
                        break
                    add(
                        s,
                        {
                            "kind": "artist",
                            "mbid": valid_id(x["mbid"]),
                            "artist": x["name"],
                            "source": "ListenBrainz listener-based discovery",
                            "reason": "Related to "
                            + name
                            + " in your library ("
                            + mode
                            + " exploration)",
                            "url": "https://musicbrainz.org/artist/" + x["mbid"],
                        },
                    )
                    if i < 3:
                        try:
                            album_items(
                                s,
                                x["mbid"],
                                x["name"],
                                "Albums by an artist related to " + name,
                                "related-album",
                            )
                        except ValueError as e:
                            if job.get("cancel") or not s.settings(True).get(
                                "discoveryOnline", False
                            ):
                                break
                            diag.error(e, operation="discovery-worker")
                            with state_lock:
                                if str(e) not in job["errors"]:
                                    job["errors"].append(str(e))
            except Exception as e:
                if job.get("cancel") or not s.settings(True).get("discoveryOnline", False):
                    break
                diag.error(e, operation="discovery-worker")
                with state_lock:
                    if str(e) not in job["errors"]:
                        job["errors"].append(str(e))
    finally:
        with state_lock:
            progress = (
                "Stopped"
                if job.get("cancel")
                else (
                    "Some online discoveries are unavailable"
                    if job["errors"]
                    else (
                        "Discoveries ready, including cached results"
                        if job.get("warnings")
                        else "Recommendations ready"
                    )
                )
            )
            job.update(running=False, updated=time.time(), progress=progress)


def snapshot(s, summary=False):
    init(s)
    with s.db() as c:
        rows = (
            []
            if summary
            else [json.loads(r[0]) for r in c.execute("SELECT value FROM discovery_items")]
        )
        feedback = {r["id"]: r["status"] for r in c.execute("SELECT * FROM discovery_feedback")}
    for r in rows:
        r["libraryStatus"] = ownership(s, r["artist"], r.get("album"))
        r["feedback"] = feedback.get(r["id"], "")
    with state_lock:
        status = dict(job)
    return {
        "profile": [] if summary else profile(s),
        "items": sorted(rows, key=lambda r: -r.get("updated", 0)),
        "job": status,
        "online": bool(s.settings(True).get("discoveryOnline", False)),
        "releasePreferences": {
            k: s.settings(True).get(key, default)
            for k, key, default in [
                ("country", "releaseCountry", "GB"),
                ("days", "releaseDays", 30),
                ("type", "releaseType", "albums"),
                ("worldwide", "releaseWorldwide", True),
                ("includeOlder", "releaseIncludeOlder", False),
                ("genre", "releaseGenre", "all"),
                ("sort", "releaseSort", "recent"),
                ("focus", "releaseFocus", "all"),
            ]
        },
    }


def start(s, b):
    init(s)
    if not s.settings(True).get("discoveryOnline", False):
        raise ValueError(
            "Enable online discovery first. Artist/album names go to MusicBrainz; artist identifiers go to ListenBrainz."
        )
    lib = profile(s)
    allowed = {a["artist"]: a for a in lib}
    name = str(b.get("artist", "")).strip()
    seed_album = str(b.get("album", "")).strip()
    mode = b.get("mode", "easy")
    if mode not in ("easy", "medium", "hard"):
        raise ValueError("Invalid exploration mode.")
    if name:
        if name not in allowed:
            raise ValueError("Choose an indexed library artist.")
        if seed_album and seed_album not in allowed[name]["albums"]:
            raise ValueError("Choose an indexed library album.")
        seeds = [name]
    else:
        if not lib:
            raise ValueError(
                "Scan your music folders first. Tagged artists are required for recommendations."
            )
        pool = lib[:40]
        random.Random(int(time.time() // 86400)).shuffle(pool)
        seeds = [a["artist"] for a in pool[:3]]
        seed_album = ""
    with state_lock:
        if job["running"]:
            return {"running": True, "seeds": seeds}
        job.update(
            running=True,
            kind="related",
            errors=[],
            warnings=[],
            retryAt=0,
            candidates=[],
            cancel=False,
            progress="Starting discovery…",
        )
    threading.Thread(target=worker, args=(s, seeds, mode, seed_album), daemon=True).start()
    return {"running": True, "seeds": seeds}


def get_route(h, path, q, s):
    if path == "/api/discovery/progress":
        with state_lock:
            status = dict(job)
        h.send_json(status)
        return True
    if path == "/api/discovery":
        h.send_json(snapshot(s, q.get("summary", [""])[0] == "1"))
        return True
    return False


def post_route(h, path, b, s):
    if not path.startswith("/api/discovery/"):
        return False
    init(s)
    if path == "/api/discovery/consent":
        enabled = b.get("enabled") is True
        from features import store_settings

        store_settings(s, {"discoveryOnline": enabled})
        if not enabled:
            with state_lock:
                job["cancel"] = True
        h.send_json({"online": enabled})
        return True
    if path == "/api/discovery/start":
        h.send_json(start(s, b))
        return True
    if path == "/api/discovery/stop":
        with state_lock:
            job["cancel"] = True
        h.send_json({"ok": True})
        return True
    if path == "/api/discovery/feedback":
        status = b.get("status", "")
        from identity import resolve

        iid = resolve(s, str(b.get("id", "")))
        if status not in ("", "saved", "dismissed"):
            raise ValueError("Invalid recommendation status.")
        with s.db() as c:
            if not c.execute("SELECT id FROM discovery_items WHERE id=?", (iid,)).fetchone():
                raise ValueError("Recommendation not found.")
            c.execute("INSERT OR REPLACE INTO discovery_feedback VALUES (?,?)", (iid, status))
        h.send_json({"ok": True})
        return True
    if path == "/api/discovery/match":
        name = str(b.get("artist", ""))
        aid = valid_id(b.get("mbid"))
        choice = None
        with state_lock:
            for x in job["candidates"]:
                if x["artist"] == name:
                    choice = next((v for v in x["choices"] if v["mbid"] == aid), None)
        if not choice:
            raise ValueError("Choose one of the proposed catalogue matches.")
        with s.db() as c:
            c.execute(
                "INSERT OR REPLACE INTO discovery_matches VALUES (?,?,?)",
                (s.norm(name), aid, choice["name"]),
            )
        h.send_json({"ok": True})
        return True
    return False
