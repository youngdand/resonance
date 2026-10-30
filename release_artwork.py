"""Cached, exact-identity artwork fallbacks for visible release cards."""

from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError
import json, re, threading, time, unicodedata, uuid
import showcase_data as data
import discovery
from contextlib import nullcontext

LOCK = threading.RLock()
HOST_LOCKS = {}
LAST = {}
COOLDOWN = {}


def norm(value):
    value = unicodedata.normalize("NFKD", str(value)).casefold()
    return "".join(c for c in value if c.isalnum() and not unicodedata.combining(c))


def title(value, typ):
    # API type suffixes are not edition names. Keep Deluxe/Live/Remaster distinctions.
    if typ in ("EP", "Single"):
        value = re.sub(r"\s*[-–]\s*" + typ + r"$", "", str(value), flags=re.I)
    return norm(value)


def candidate(url, source, link):
    image = data.image_url(url)
    u = urlsplit(link or "")
    hosts = {
        "Apple Music": ("music.apple.com", "itunes.apple.com"),
        "Deezer": ("www.deezer.com", "deezer.com"),
        "Cover Art Archive": ("musicbrainz.org",),
    }
    if not image or u.scheme != "https" or u.hostname not in hosts.get(source, ()) or u.username:
        return None
    return {"url": image, "source": source, "sourceUrl": link}


def apple(records, item):
    result = []
    for row in records.get("results", []):
        if (
            row.get("wrapperType") != "collection"
            or norm(row.get("artistName", "")) != norm(item["artist"])
            or title(row.get("collectionName", ""), item.get("releaseType"))
            != title(item["album"], item.get("releaseType"))
        ):
            continue
        art = row.get("artworkUrl100") or row.get("artworkUrl60", "")
        art = re.sub(r"/\d+x\d+bb\.", "/600x600bb.", art)
        found = candidate(art, "Apple Music", row.get("collectionViewUrl", ""))
        if found:
            result.append(found)
    return result


def deezer(records, item):
    result = []
    for row in records.get("data", []):
        if norm((row.get("artist") or {}).get("name", "")) != norm(item["artist"]) or title(
            row.get("title", ""), item.get("releaseType")
        ) != title(item["album"], item.get("releaseType")):
            continue
        found = candidate(
            row.get("cover_big") or row.get("cover_medium") or row.get("cover", ""),
            "Deezer",
            row.get("link", ""),
        )
        if found:
            result.append(found)
    return result


def caa(records, item):
    result = []
    for image in records.get("images", []):
        if not image.get("front") or not image.get("approved"):
            continue
        thumbnails = image.get("thumbnails") or {}
        art = thumbnails.get("500") or thumbnails.get("large") or image.get("image", "")
        # The archive documents historic HTTP URLs; request the HTTPS equivalent only.
        if art.startswith("http://"):
            art = "https://" + art[7:]
        found = candidate(
            art,
            "Cover Art Archive",
            "https://musicbrainz.org/release-group/" + item["mbid"],
        )
        if found:
            result.append(found)
    return result


def request(s, url):
    import supplier_http

    value = json.loads(
        supplier_http.read(s, url, accept="application/json", limit=1_000_000, timeout=5)
    )
    if not isinstance(value, dict):
        raise ValueError("Invalid artwork metadata.")
    return value


def init(s):
    import storage

    storage.ensure_schema(
        s,
        "release_artwork",
        "CREATE TABLE IF NOT EXISTS release_artwork_cache (key TEXT PRIMARY KEY,value TEXT,updated REAL)",
    )


def provider(s, url, parse, item):
    with s.db() as c:
        row = c.execute(
            "SELECT value,updated FROM release_artwork_cache WHERE key=?", (url,)
        ).fetchone()
    if row:
        value = json.loads(row["value"])
        ttl = 900 if value.get("failed") else 7 * 86400 if value.get("candidates") else 6 * 3600
        if time.time() - row["updated"] < ttl:
            return value.get("candidates", [])
    if not s.settings(True).get("discoveryOnline"):
        return json.loads(row["value"]).get("candidates", []) if row else []
    try:
        value = {"candidates": parse(request(s, url), item)}
    except Exception as exc:
        s.diag.event(
            "artwork-provider-error",
            "WARNING",
            service=urlsplit(url).hostname,
            errorType=type(exc).__name__,
            status=getattr(exc, "code", None),
        )
        value = {
            "candidates": json.loads(row["value"]).get("candidates", []) if row else [],
            "failed": True,
        }
    with s.db() as c:
        c.execute(
            "INSERT OR REPLACE INTO release_artwork_cache VALUES (?,?,?)",
            (url, json.dumps(value), time.time()),
        )
    return value["candidates"]


def find(s, ident, failed=""):
    init(s)
    with s.db() as c:
        row = c.execute("SELECT value FROM discovery_items WHERE id=?", (ident,)).fetchone()
    if not row:
        raise ValueError("Release not found.")
    item = json.loads(row[0])
    rejected = {failed} if isinstance(failed, str) and len(failed) <= 2500 else set()
    if time.time() - item.get("artworkRejectedAt", 0) < 86400:
        rejected.update(item.get("artworkRejected", []))
    existing = data.image_url(item.get("artwork"))
    if existing and existing not in rejected:
        return {
            "id": ident,
            "artwork": existing,
            "artworkSource": item.get("artworkSource", "Publisher"),
            "artworkSourceUrl": item.get("artworkSourceUrl", ""),
        }
    country = str(item.get("country", "GB")).upper()
    if not re.fullmatch("[A-Z]{2}", country):
        country = "GB"
    params = {
        "term": item["artist"] + " " + item["album"],
        "entity": "album",
        "media": "music",
        "country": country,
        "limit": 25,
    }
    providers = [
        ("https://itunes.apple.com/search?" + urlencode(params), apple),
        (
            "https://api.deezer.com/search/album?"
            + urlencode({"q": item["artist"] + " " + item["album"], "limit": 25}),
            deezer,
        ),
    ]
    try:
        mbid = str(uuid.UUID(item.get("mbid", "")))
    except (ValueError, TypeError, AttributeError):
        mbid = ""
    if mbid:
        providers.append(("https://coverartarchive.org/release-group/" + mbid, caa))
    found = None
    # Query results depend only on artist/album/market; both release tabs reuse them.
    for url, parser in providers:
        found = next(
            (c for c in provider(s, url, parser, item) if c["url"] not in rejected),
            None,
        )
        if found:
            break
    update = {}
    if found:
        update = {
            "artwork": found["url"],
            "artworkSource": found["source"],
            "artworkSourceUrl": found["sourceUrl"],
        }
    if rejected:
        update.update(artworkRejected=list(rejected)[:8], artworkRejectedAt=time.time())
    if update:
        with s.db() as c:
            c.execute("BEGIN IMMEDIATE")
            fresh = c.execute("SELECT value FROM discovery_items WHERE id=?", (ident,)).fetchone()
            if fresh:
                current = json.loads(fresh[0])
                current.update(update)
                c.execute(
                    "UPDATE discovery_items SET value=? WHERE id=?",
                    (json.dumps(current), ident),
                )
    return {
        "retryAfter": 900 if not found else 7 * 86400,
        "id": ident,
        **{
            k: v
            for k, v in update.items()
            if k.startswith("artwork") and k not in ("artworkRejected", "artworkRejectedAt")
        },
        "artwork": found["url"] if found else "",
    }
