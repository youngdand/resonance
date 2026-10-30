"""Small shared publisher indexes; conservative release matching, no search scraping."""

from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.request import Request
from urllib.parse import urlsplit, urljoin, quote_plus, urlencode
from html import unescape
import json, re, threading, time, unicodedata, xml.etree.ElementTree as ET
import showcase_data as data

SOURCES = [
    ("Pitchfork", "https://pitchfork.com/reviews/albums/", "index"),
    ("NME", "https://www.nme.com/reviews/album/feed", "feed"),
    (
        "The Guardian",
        "https://www.theguardian.com/music/music+tone/albumreview/rss",
        "feed",
    ),
    ("Metacritic", "https://www.metacritic.com/music/", "link"),
    ("Indie Is Not A Genre", "https://www.indieisnotagenre.com/reviews/", "index"),
    ("Album of the Year", "https://www.albumoftheyear.org/", "link"),
    (
        "Rolling Stone",
        "https://www.rollingstone.com/music/music-album-reviews/feed/",
        "feed",
    ),
    ("AnyDecentMusic", "https://www.anydecentmusic.com/", "link"),
    (
        "No Clean Singing",
        "https://www.nocleansinging.com/category/reviews/album-reviews/feed/",
        "feed",
    ),
]
LOCK = threading.RLock()
INDEX_LOCKS = {}
EXECUTOR = ThreadPoolExecutor(max_workers=4)
# Publisher search endpoints look beyond the latest feed/page, without a third-party search key.
SEARCHES = [
    ("Silent Radio", "https://www.silentradio.co.uk/feed/", "search-feed"),
    ("Clash", "https://www.clashmusic.com/wp-json/wp/v2/posts", "search-api"),
    ("The Quietus", "https://thequietus.com/wp-json/wp/v2/posts", "search-api"),
    (
        "Indie Is Not A Genre",
        "https://www.indieisnotagenre.com/wp-json/wp/v2/posts",
        "search-api",
    ),
]


def preview(text, limit=80):
    return data.short_quote(plain(text), limit)


def words(value):
    value = unicodedata.normalize("NFKD", str(value)).casefold()
    return " ".join(
        re.findall(r"[^\W_]+", "".join(c for c in value if not unicodedata.combining(c)))
    )


def phrase(needle, haystack):
    return bool(words(needle)) and " " + words(needle) + " " in " " + words(haystack) + " "


def matches(row, item):
    title = unescape(row.get("title", ""))
    # Album and artist must occur as whole phrases; URL slug is additional evidence only.
    return phrase(item["album"], title) and (
        phrase(item["artist"], title)
        or (
            row.get("albumOnly")
            and phrase(item["artist"], urlsplit(row["url"]).path.replace("-", " "))
        )
    )


def allowed(url, base):
    u = urlsplit(url)
    b = urlsplit(base)
    return (
        u.scheme == "https"
        and u.hostname == b.hostname
        and not u.username
        and u.port in (None, 443)
    )


class Text(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.parts = []
        self.feed(text)

    def handle_data(self, text):
        self.parts.append(text)


def plain(text):
    return unescape(" ".join(Text(str(text or "")).parts))


class Links(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.rows = []
        self.current = None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.current = {"url": dict(attrs).get("href", ""), "title": ""}

    def handle_data(self, text):
        if self.current is not None:
            self.current["title"] += " " + text

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            self.rows.append(self.current)
            self.current = None


def parse_index(text, base, kind):
    rows = []
    if kind == "feed":
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise ValueError("Unexpected feed document.")
        root = ET.fromstring(text)
        if root.tag not in ("rss", "{http://www.w3.org/2005/Atom}feed"):
            raise ValueError("Publisher did not return a feed.")
        for r in root.findall(".//item")[:100]:
            rows.append(
                {
                    "title": r.findtext("title") or "",
                    "url": r.findtext("link") or "",
                    "excerpt": preview(r.findtext("description") or ""),
                    "author": r.findtext("{http://purl.org/dc/elements/1.1/}creator") or "",
                    "published": r.findtext("pubDate") or "",
                }
            )
    else:
        if urlsplit(base).hostname == "pitchfork.com":
            rows = [
                {"title": o.get("name", ""), "url": o.get("url", ""), "albumOnly": True}
                for o in data.Metadata(text).objects()
                if o.get("@type") == "ListItem"
            ]
        else:
            rows = Links(text).rows
    result = {}
    for row in rows:
        url = urljoin(base, row["url"])
        path = urlsplit(url).path
        if (
            not allowed(url, base)
            or urlsplit(url).path.rstrip("/") == urlsplit(base).path.rstrip("/")
            or (kind == "index" and not ("review" in path and "/artist/" not in path))
        ):
            continue
        row["url"] = url
        row["title"] = plain(row["title"]).strip()[:500]
        if row["title"]:
            result[url] = row
    return list(result.values())[:100]


def fetch(url, version):
    import supplier_http

    return supplier_http.read(
        supplier_http.application,
        url,
        accept="application/rss+xml, application/xml, text/html",
        timeout=6,
    ).decode("utf-8-sig", errors="replace")


def init(s):
    import storage

    storage.ensure_schema(
        s,
        "review_sources",
        "CREATE TABLE IF NOT EXISTS review_source_cache (key TEXT PRIMARY KEY,value TEXT,updated REAL)",
    )


def cached(s, key, loader, ttl=6 * 3600):
    with s.db() as c:
        row = c.execute(
            "SELECT value,updated FROM review_source_cache WHERE key=?", (key,)
        ).fetchone()
    if row:
        previous = json.loads(row["value"])
        if time.time() - row["updated"] < (min(ttl, 3600) if previous.get("failed") else ttl):
            return previous
    if not s.settings(True).get("discoveryOnline", False):
        return (
            {**json.loads(row["value"]), "stale": True}
            if row
            else {"rows": [], "status": "Offline; no cached index"}
        )
    try:
        value = loader()
        value["retrievedAt"] = time.time()
    except Exception as exc:
        s.diag.event(
            "review-source-error",
            "WARNING",
            service=urlsplit(key.split(":", 1)[1]).hostname,
            errorType=type(exc).__name__,
            status=getattr(exc, "code", None),
        )
        value = (
            {
                **json.loads(row["value"]),
                "stale": True,
                "status": "Unavailable; using cached information",
                "failed": True,
                "retrievedAt": json.loads(row["value"]).get("retrievedAt", row["updated"]),
            }
            if row
            else {
                "rows": [],
                "status": "Temporarily unavailable; use source search",
                "failed": True,
            }
        )
    # Negative cache prevents repeated blocked requests every time an album is opened.
    with s.db() as c:
        c.execute(
            "INSERT OR REPLACE INTO review_source_cache VALUES (?,?,?)",
            (key, json.dumps(value), time.time()),
        )
    return value


def article(text, row, name):
    meta = data.Metadata(text)
    objects = list(meta.objects())
    ratings = []
    author = row.get("author", "")
    excerpt = row.get("excerpt", "")
    published = row.get("published", "")
    for obj in objects:
        types = obj.get("@type", [])
        types = [types] if isinstance(types, str) else types
        if not any(
            t in types for t in ("Review", "MusicReview", "Article", "NewsArticle", "BlogPosting")
        ):
            continue
        # Only explicit professional reviewRating; never audience AggregateRating.
        if any(t in types for t in ("Review", "MusicReview")):
            r = data.score(obj.get("reviewRating"), name, row["url"])
            if r:
                r["url"] = row["url"]
                ratings.append(r)
        author = data.author_name(obj.get("author")) or author
        published = obj.get("datePublished") or published
        excerpt = preview(obj.get("description") or obj.get("reviewBody") or excerpt)
    excerpt = preview(
        excerpt or meta.meta.get("og:description", "") or meta.meta.get("twitter:description", "")
    )
    if len(excerpt.split()) < 30:
        # Older publisher pages may expose article text but no schema/description.
        import release_sources

        tree = release_sources.Tree(text).root
        body = next(
            (
                n
                for n in tree.all()
                if any(
                    c in n.attrs.get("class", "").split()
                    for c in ("postcontent", "entry-content", "article-content")
                )
            ),
            None,
        )
        if body:
            paragraph = next((p.text for p in body.all("p") if len(p.text.split()) >= 30), "")
            if paragraph:
                excerpt = preview(paragraph)
    author = author or meta.meta.get("author", "")
    return {
        "publisher": name,
        "url": row["url"],
        "excerpt": excerpt,
        "author": author,
        "published": published,
        "ratings": ratings[:1],
        "tracks": [],
        "review": True,
        "title": row.get("title", ""),
        "kind": (
            "review"
            if "review" in (row.get("title", "") + " " + row["url"]).casefold()
            else "feature"
        ),
    }


def search_index(text, url, kind):
    if kind == "search-feed":
        return parse_index(text, url, "feed")
    records = json.loads(text)
    if not isinstance(records, list):
        raise ValueError("Publisher search format changed.")
    rows = []
    for obj in records[:10]:
        link = obj.get("link", "")
        if not allowed(link, url):
            continue
        rows.append(
            {
                "title": plain((obj.get("title") or {}).get("rendered", "")),
                "url": link,
                "excerpt": preview((obj.get("excerpt") or {}).get("rendered", "")),
                "published": obj.get("date", ""),
            }
        )
    return rows


def lookup(s, item):
    init(s)

    def one(source):
        name, url, kind = source
        status = {
            "name": name,
            "url": url,
            "searchUrl": "https://www.google.com/search?q="
            + quote_plus(
                "site:"
                + urlsplit(url).hostname
                + " "
                + item["artist"]
                + " "
                + item["album"]
                + " review"
            ),
            "status": "External search · ratings not imported",
            "kind": kind,
        }
        if kind == "link":
            return [], status
        targeted = kind.startswith("search-")
        if targeted:
            query = item["artist"] + " " + item["album"]
            params = (
                {"s": query}
                if kind == "search-feed"
                else {
                    "search": query,
                    "per_page": 5,
                    "_fields": "link,title,excerpt,date",
                }
            )
            url = url + "?" + urlencode(params)
        with LOCK:
            index_lock = INDEX_LOCKS.setdefault(url, threading.RLock())
        with index_lock:
            # One index per publisher, shared by all albums; release/library identifiers stay local.
            index = cached(
                s,
                "index-v2:" + url,
                lambda: {
                    "rows": (
                        search_index(fetch(url, s.diag.VERSION), url, kind)
                        if targeted
                        else parse_index(fetch(url, s.diag.VERSION), url, kind)
                    ),
                    "status": ("Album search checked" if targeted else "Recent index checked"),
                },
            )
        status["status"] = index["status"]
        status["stale"] = index.get("stale", False)
        found = [r for r in index.get("rows", []) if matches(r, item)][:1]
        publications = []
        for row in found:

            def load():
                return {
                    "publication": article(fetch(row["url"], s.diag.VERSION), row, name),
                    "status": "Review matched",
                }

            record = cached(s, "article-v2:" + row["url"], load, 7 * 86400)
            pub = record.get("publication")
            if not pub:
                # A matching feed headline is still a useful attributed review link.
                pub = {
                    "publisher": name,
                    "url": row["url"],
                    "excerpt": row.get("excerpt", ""),
                    "author": row.get("author", ""),
                    "published": row.get("published", ""),
                    "ratings": [],
                    "tracks": [],
                    "review": True,
                    "title": row.get("title", ""),
                    "kind": (
                        "review"
                        if "review" in (row.get("title", "") + " " + row["url"]).casefold()
                        else "feature"
                    ),
                }
            pub = {
                **pub,
                "stale": record.get("stale", False) or index.get("stale", False),
            }
            publications.append(pub)
            status["status"] = "Matched review" + (" · cached" if pub["stale"] else "")
        if not found and status["status"] in (
            "Recent index checked",
            "Album search checked",
        ):
            status["status"] = "No matching coverage found"
        return publications, status

    # Fixed pool bounds network work and keeps independent publisher failures isolated.
    results = list(EXECUTOR.map(one, SOURCES + SEARCHES))
    publications = {}
    for pubs, _ in results:
        for pub in pubs:
            publications[pub["url"]] = pub
    return {
        "publications": list(publications.values()),
        "reviewSources": [status for _, status in results],
    }


def for_release(s, ident):
    with s.db() as c:
        row = c.execute("SELECT value FROM discovery_items WHERE id=?", (ident,)).fetchone()
    if not row:
        raise ValueError("Release not found. Refresh discovery.")
    item = json.loads(row[0])
    result = lookup(s, item)
    import release_context

    result["publications"] += release_context.lookup(s, item)
    # Persist verified critic metadata so score filters can use it on subsequent visits.
    ratings = [rating for pub in result["publications"] for rating in pub.get("ratings", [])]
    readable = [pub for pub in result["publications"] if pub.get("excerpt")]
    if ratings or readable:
        with s.db() as c:
            c.execute("BEGIN IMMEDIATE")
            fresh = c.execute("SELECT value FROM discovery_items WHERE id=?", (ident,)).fetchone()
            if fresh:
                current = json.loads(fresh[0])
                merged = {(x.get("publisher"), x.get("url")): x for x in current.get("ratings", [])}
                merged.update({(x["publisher"], x["url"]): x for x in ratings})
                current["ratings"] = list(merged.values())
                if readable:
                    lead = next((p for p in readable if p.get("kind") == "review"), readable[0])
                    current["coveragePreview"] = {
                        "text": preview(lead["excerpt"], 40),
                        "publisher": lead["publisher"],
                        "url": lead["url"],
                        "kind": lead.get("kind", "feature"),
                    }
                c.execute(
                    "UPDATE discovery_items SET value=? WHERE id=?",
                    (json.dumps(current), ident),
                )
    return result
