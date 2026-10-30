"""On-demand, cached release dossiers from known publisher pages."""

from urllib.request import Request
from supplier_http import urlopen
from urllib.parse import urlsplit, quote_plus
import json, re, threading, time
import showcase_data as data
import release_sources as sources

lock = threading.RLock()
resource_locks = {}


def normalize(text):
    return re.sub(r"[^\w]+", "", str(text).casefold())


def parse(text, item, url):
    meta = data.Metadata(text)
    objects = list(meta.objects())
    album = next(
        (
            o
            for o in objects
            if o.get("@type") == "MusicAlbum"
            and normalize(o.get("name", "")) == normalize(item["album"])
        ),
        {},
    )
    title = meta.meta.get("og:title", "").split(" | ")[0]
    if not album and normalize(title) != normalize(item["album"]):
        raise ValueError("Publisher page did not match this release; its details were not adopted.")
    artist = album.get("byArtist") or {}
    if (
        isinstance(artist, dict)
        and artist.get("name")
        and normalize(artist["name"]) != normalize(item["artist"])
    ):
        raise ValueError("Publisher artist did not match this release.")
    publisher = "AllMusic" if urlsplit(url).hostname == "www.allmusic.com" else "Official Charts"
    result = {
        "publisher": publisher,
        "url": url,
        "artwork": data.image_url(album.get("image") or meta.meta.get("og:image", "")),
        "genres": album.get("genre", []),
        "tracks": [],
        "ratings": [],
        "excerpt": "",
        "author": "",
        "published": album.get("datePublished", ""),
        "label": "",
        "previewVersion": 2,
    }
    if isinstance(result["genres"], str):
        result["genres"] = [result["genres"]]
    for track in album.get("track", [])[:100]:
        if isinstance(track, dict) and track.get("name"):
            result["tracks"].append(
                {
                    "title": str(track["name"])[:200],
                    "position": track.get("position"),
                    "duration": str(track.get("duration", ""))[:40],
                }
            )
    # A publisher-authored Review is separate from audience AggregateRating/user reviews.
    for review in objects:
        if review.get("@type") != "Review" or data.author_name(review.get("author")) != "AllMusic":
            continue
        reviewed = review.get("itemReviewed") or {}
        if (
            isinstance(reviewed, dict)
            and reviewed.get("@id")
            and reviewed["@id"].rstrip("/") != url.rstrip("/")
        ):
            continue
        rating = data.score(review.get("reviewRating"), publisher, url)
        if rating:
            result["ratings"].append(rating)
        result["excerpt"] = data.short_quote(review.get("reviewBody", ""), 80)
        result["author"] = item.get("reviewAuthor") or "AllMusic"
        break
    if publisher == "Official Charts":
        result["excerpt"] = data.short_quote(meta.meta.get("og:description", ""))
        result["author"] = "Official Charts"
    result["label"] = data.author_name(album.get("recordLabel", ""))
    return result


def init(s):
    import storage

    storage.ensure_schema(
        s,
        "release_details",
        "CREATE TABLE IF NOT EXISTS release_dossiers (url TEXT PRIMARY KEY,value TEXT,updated REAL)",
    )


def page(s, url, item):
    host = urlsplit(url).hostname
    if not data.public_link(url) or not (
        (host == "www.allmusic.com" and urlsplit(url).path.startswith("/album/"))
        or (
            host == "www.officialcharts.com"
            and urlsplit(url).path.startswith(("/albums/", "/songs/"))
        )
    ):
        raise ValueError("Unsupported publisher page.")
    with s.db() as c:
        row = c.execute("SELECT value,updated FROM release_dossiers WHERE url=?", (url,)).fetchone()
    if (
        row
        and time.time() - row["updated"] < 7 * 86400
        and json.loads(row["value"]).get("previewVersion") == 2
    ):
        return json.loads(row["value"])
    if not s.settings(True).get("discoveryOnline", False):
        if row:
            return {**json.loads(row["value"]), "stale": True}
        raise ValueError(
            "Enable online discovery to load publisher details. Cached information remains available."
        )
    try:
        with lock:
            resource_lock = resource_locks.setdefault(url, threading.RLock())
        with resource_lock:
            with s.db() as c:
                row = c.execute(
                    "SELECT value,updated FROM release_dossiers WHERE url=?", (url,)
                ).fetchone()
            if (
                row
                and time.time() - row["updated"] < 7 * 86400
                and json.loads(row["value"]).get("previewVersion") == 2
            ):
                return json.loads(row["value"])
            with urlopen(Request(url, headers={"Accept": "text/html"}), timeout=8) as response:
                raw = response.read(3_000_001)
            value = parse(raw.decode("utf-8-sig"), item, url)
            with s.db() as c:
                c.execute(
                    "INSERT OR REPLACE INTO release_dossiers VALUES (?,?,?)",
                    (url, json.dumps(value), time.time()),
                )
            return value
    except Exception:
        if row:
            return {**json.loads(row["value"]), "stale": True}
        raise ValueError(
            host
            + " details are unavailable. The release and its original source link remain available."
        ) from None


def dossier(s, ident):
    init(s)
    with s.db() as c:
        row = c.execute("SELECT value FROM discovery_items WHERE id=?", (ident,)).fetchone()
    if not row:
        raise ValueError("Release not found. Refresh the discovery page.")
    item = json.loads(row[0])
    with s.db() as c:
        feedback = c.execute(
            "SELECT status FROM discovery_feedback WHERE id=?", (ident,)
        ).fetchone()
    item["feedback"] = feedback[0] if feedback else ""
    publications = []
    warnings = []
    seen = set()
    for source in item.get("sources") or [
        {"name": item.get("source", ""), "url": item.get("url", "")}
    ]:
        url = source.get("url", "")
        if url in seen:
            continue
        seen.add(url)
        if len(publications) >= 3:
            break
        try:
            publications.append(page(s, url, item))
        except ValueError as exc:
            warnings.append(str(exc))
    import release_context

    publications += release_context.lookup(s, item)
    for publication in publications:
        if not data.image_url(item.get("artwork")) and publication.get("artwork"):
            item.update(
                artwork=publication["artwork"],
                artworkSource=publication["publisher"],
                artworkSourceUrl=publication["url"],
            )
        for field in ("label", "genres"):
            if publication.get(field):
                item[field] = publication[field]
    ratings = {(r.get("publisher"), r.get("url")): r for r in item.get("ratings", [])}
    for publication in publications:
        ratings.update(
            {(r.get("publisher"), r.get("url")): r for r in publication.get("ratings", [])}
        )
    if ratings:
        item["ratings"] = list(ratings.values())
    item["overview"] = data.overview(item)
    # Store facts only, preserving feedback and transfer state in their own tables.
    with s.db() as c:
        c.execute("BEGIN IMMEDIATE")
        fresh = c.execute("SELECT value FROM discovery_items WHERE id=?", (ident,)).fetchone()
        if fresh:
            current = json.loads(fresh[0])
            current.update(
                {
                    k: item[k]
                    for k in (
                        "artwork",
                        "artworkSource",
                        "artworkSourceUrl",
                        "label",
                        "genres",
                        "ratings",
                    )
                    if item.get(k)
                }
            )
            c.execute(
                "UPDATE discovery_items SET value=? WHERE id=?",
                (json.dumps(current), ident),
            )
    query = quote_plus(item["artist"] + " " + item["album"] + " review")
    return {
        "item": item,
        "publications": publications,
        "warnings": warnings,
        "researchLinks": [
            {
                "name": "Search for more reviews",
                "url": "https://www.google.com/search?q=" + query,
            },
            {
                "name": "Find on Bandcamp",
                "url": "https://bandcamp.com/search?q="
                + quote_plus(item["artist"] + " " + item["album"]),
            },
        ],
        "updated": time.time(),
    }
