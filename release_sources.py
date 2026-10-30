"""Independent release listings and optional, bounded Apple artist-catalogue checks.
Only public metadata is read; no previews, cover images or music are downloaded.
"""

from html.parser import HTMLParser
from urllib.request import Request
from supplier_http import urlopen
from urllib.parse import urlencode, urlsplit, urljoin
from urllib.error import HTTPError, URLError
from datetime import datetime, timedelta
import hashlib, json, re, time, unicodedata, xml.etree.ElementTree as ET
import discovery as d
import release_genres as genres
import showcase_data as showcase

CHARTS = "https://www.officialcharts.com/new-releases/"
ALLMUSIC = "https://www.allmusic.com/newreleases"
RSS = "https://www.allmusic.com/rss/newreleases"
APPLE = "https://itunes.apple.com/search?"
HOSTS = {"www.officialcharts.com", "www.allmusic.com", "itunes.apple.com"}


class Node:
    def __init__(self, tag="", attrs=()):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []

    @property
    def text(self):
        return " ".join(
            " ".join(c.text if isinstance(c, Node) else c for c in self.children).split()
        )

    def all(self, tag=None, cls=None):
        for c in self.children:
            if isinstance(c, Node):
                if (tag is None or c.tag == tag) and (
                    cls is None or cls in c.attrs.get("class", "").split()
                ):
                    yield c
                yield from c.all(tag, cls)

    def first(self, tag=None, cls=None):
        return next(self.all(tag, cls), Node())


class Tree(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self.stack[-1].tag not in ("script", "style"):
            self.stack[-1].children.append(data)


def safe_url(url, host):
    return url if urlsplit(url).scheme == "https" and urlsplit(url).hostname == host else ""


def charts(text):
    tree = Tree(text).root
    items = []
    sections = 0
    for section in tree.all("section"):
        label = section.attrs.get("label", "")
        match = re.fullmatch(
            r"New Music Friday (album|song) releases - ([A-Za-z]+ \d{1,2} \d{4})",
            label,
            re.I,
        )
        if not match:
            continue
        day = datetime.strptime(match[2], "%B %d %Y").date().isoformat()
        sections += 1
        for card in section.all(cls="chart-item"):
            title = card.first(cls="chart-name")
            artist = card.first(cls="chart-artist")
            if title.text and artist.text:
                items.append(
                    {
                        "artist": artist.text,
                        "album": title.text,
                        "releaseDate": day,
                        "releaseType": ("Single" if match[1].casefold() == "song" else "Album"),
                        "genres": [],
                        "source": "Official Charts UK release listings",
                        "url": safe_url(
                            urljoin(CHARTS, title.attrs.get("href", "")),
                            "www.officialcharts.com",
                        ),
                        "market": "GB",
                        "dateBasis": "release-listing",
                        "artwork": showcase.image_attrs(
                            (
                                card.first(cls="chart-image-large")
                                if card.first(cls="chart-image-large").attrs
                                else card.first("img")
                            ).attrs
                        ),
                    }
                )
    if not sections or not items:
        raise ValueError(
            "Official Charts page format changed or has no release listings. Cached results have been kept."
        )
    return items


ARCHIVE = "https://www.officialcharts.com/news/new-releases/"


def archive_date(url):
    path = urlsplit(url).path.strip("/").split("/")[-1]
    patterns = (
        (r"(\d{1,2})-([a-z]+)-(\d{4})", "%d-%B-%Y"),
        (r"([a-z]+)-(\d{1,2})-(\d{4})", "%B-%d-%Y"),
    )
    for pattern, fmt in patterns:
        match = re.search(pattern, path, re.I)
        if match:
            try:
                return datetime.strptime("-".join(match.groups()), fmt).date().isoformat()
            except ValueError:
                continue
    return None


def archive_index(text):
    entries = {}
    for link in Tree(text).root.all("a"):
        url = safe_url(urljoin(ARCHIVE, link.attrs.get("href", "")), "www.officialcharts.com")
        if not url or not urlsplit(url).path.startswith("/chart-news/new-music-friday-"):
            continue
        day = archive_date(url)
        if day:
            entries.setdefault(day, {"date": day, "url": url})
    if not entries:
        raise ValueError(
            "Official Charts release archive format changed. Cached results have been kept."
        )
    return sorted(entries.values(), key=lambda row: row["date"], reverse=True)


def allmusic(text):
    tree = Tree(text).root
    headline = next((n for n in tree.all("h1") if n.attrs.get("data-startweek")), None)
    if not headline:
        raise ValueError("AllMusic page format changed. Cached results have been kept.")
    day = datetime.strptime(headline.attrs["data-startweek"], "%Y%m%d").date().isoformat()
    items = []
    metadata = showcase.album_metadata(text)
    for card in tree.all("article", "newReleaseItem"):
        artist = card.first(cls="artist").text
        album = card.first(cls="title").text
        link = card.first(cls="title").first("a").attrs.get("href", "")
        if artist and album:
            items.append(
                {
                    "artist": artist,
                    "album": album,
                    "releaseDate": day,
                    "releaseType": "Album",
                    "genres": [a.text for a in card.first(cls="genres").all("a") if a.text],
                    "source": "AllMusic featured release listings",
                    "url": safe_url(urljoin(ALLMUSIC, link), "www.allmusic.com"),
                    "market": "unverified",
                    "dateBasis": "listing-week",
                    "artwork": showcase.image_attrs(card.first("img").attrs),
                    "label": card.first(cls="labels").text,
                    **{
                        k: v
                        for k, v in metadata.get(urljoin(ALLMUSIC, link).rstrip("/"), {}).items()
                        if v
                    },
                }
            )
    if not items:
        raise ValueError(
            "AllMusic returned no featured album entries. Cached results have been kept."
        )
    return items


def newsletter(text):
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("Unsupported release feed document.")
    root = ET.fromstring(text)
    items = []
    for entry in root.findall("./channel/item"):
        match = re.search(r"\d{4}-\d{2}-\d{2}", entry.findtext("title", ""))
        if not match:
            continue
        for li in Tree(entry.findtext("description", "")).root.all("li"):
            links = list(li.all("a"))
            artist = next((a.text for a in links if "/artist/" in a.attrs.get("href", "")), "")
            album = next((a for a in links if "/album/" in a.attrs.get("href", "")), None)
            if artist and album:
                items.append(
                    {
                        "artist": artist,
                        "album": album.text,
                        "releaseDate": match[0],
                        "releaseType": "Album",
                        "genres": [],
                        "source": "AllMusic release newsletter",
                        "url": safe_url(album.attrs.get("href", ""), "www.allmusic.com"),
                        "market": "unverified",
                        "dateBasis": "listing-week",
                    }
                )
    if not items:
        raise ValueError("AllMusic newsletter has no album entries. Cached results have been kept.")
    return items


def fetch(s, url, parser, ttl=12 * 3600):
    """Cache parsed valid metadata only; one bounded attempt, independent host failures."""
    host = urlsplit(url).hostname
    if host not in HOSTS or urlsplit(url).scheme != "https":
        raise ValueError("Unsupported release service.")
    key = "release-provider-v2:" + url

    def cached():
        with s.db() as c:
            return c.execute(
                "SELECT value,updated FROM discovery_cache WHERE key=?", (key,)
            ).fetchone()

    row = cached()
    if row and time.time() - row["updated"] < ttl:
        return json.loads(row["value"])
    if not s.settings(True).get("discoveryOnline") or d.job.get("cancel"):
        raise ValueError("Discovery stopped.")
    cooldown = d.service_cooldowns.get(host, 0)
    try:
        if cooldown > time.time():
            raise ValueError("Provider is cooling down after a failed request.")
        with d.fetch_lock:
            row = cached()
            if row and time.time() - row["updated"] < ttl:
                return json.loads(row["value"])
            pace = 3.1 if host == "itunes.apple.com" else 1.1
            remaining = pace - (time.monotonic() - d.last_fetch.get(host, 0))
            if remaining > 0:
                d.wait_for_retry(s, remaining)
            if d.job.get("cancel"):
                raise ValueError("Discovery stopped.")
            try:
                with urlopen(
                    Request(
                        url,
                        headers={"Accept": "application/json,text/html,application/rss+xml"},
                    ),
                    timeout=8,
                ) as response:
                    raw = response.read(3_000_001)
                value = parser(raw.decode("utf-8-sig"))
                with s.db() as c:
                    c.execute(
                        "INSERT OR REPLACE INTO discovery_cache VALUES (?,?,?)",
                        (key, json.dumps(value), time.time()),
                    )
                d.service_cooldowns.pop(host, None)
                return value
            finally:
                d.last_fetch[host] = time.monotonic()
    except Exception as exc:
        if d.job.get("cancel") or not s.settings(True).get("discoveryOnline"):
            raise ValueError("Discovery stopped.") from None
        status = exc.code if isinstance(exc, HTTPError) else None
        d.diag.event(
            "release-provider-error",
            "WARNING",
            service=host,
            status=status,
            errorType=type(exc).__name__,
        )
        delay = (
            d.retry_delay(
                (exc.headers.get("Retry-After") if getattr(exc, "headers", None) else None),
                60,
            )
            if status in (429, 503)
            else 60
        )
        if not isinstance(exc, ValueError):
            d.service_cooldowns[host] = time.time() + max(60, delay)
        if isinstance(exc, HTTPError):
            exc.close()
        if row and time.time() - row["updated"] < 30 * 86400:
            d.add_warning(
                host
                + " is unavailable; using cached release listings from "
                + time.strftime("%d %b %Y", time.localtime(row["updated"]))
                + "."
            )
            return json.loads(row["value"])
        raise ValueError(
            host
            + " is unavailable"
            + (" (HTTP " + str(status) + ")" if status else "")
            + ". Other sources and cached releases remain available."
        ) from None


def key(s, artist, album):
    import identity

    return identity.release_key(artist, album)


def listings(s, country, worldwide=True, begin=None, end=None, on_batch=None, coverage=None):
    sources = []
    all_rows = []
    if country == "GB":
        sources.append(("Official Charts", CHARTS, charts))
    if worldwide:
        sources.append(("AllMusic", ALLMUSIC, allmusic))
    for name, url, parser in sources:
        if d.job.get("cancel"):
            break
        with d.state_lock:
            d.job["progress"] = "Reading " + name + " release listings…"
        try:
            batch = fetch(s, url, parser)
            all_rows.extend(batch)
            if on_batch:
                on_batch(batch)
        except ValueError as exc:
            if d.job.get("cancel"):
                break
            d.add_warning(str(exc))
            if name == "AllMusic":
                try:
                    all_rows.extend(fetch(s, RSS, newsletter))
                except ValueError as fallback:
                    d.add_warning(str(fallback))
    if country == "GB" and begin and end and not d.job.get("cancel"):
        expected = {
            (begin + timedelta(days=i)).isoformat()
            for i in range((end - begin).days + 1)
            if (begin + timedelta(days=i)).weekday() == 4
        }
        imported = {row["releaseDate"] for row in all_rows if row["market"] == "GB"}
        entries = {}
        missing = expected - imported
        if missing:
            # Normally one index covers all 13 weeks; bounded pagination handles smaller index pages.
            for page in range(3):
                if d.job.get("cancel"):
                    break
                try:
                    index = fetch(
                        s,
                        ARCHIVE + ("?page=" + str(page) if page else ""),
                        archive_index,
                    )
                except ValueError as exc:
                    d.add_warning(str(exc))
                    break
                before = len(entries)
                for entry in index:
                    if begin.isoformat() <= entry["date"] <= end.isoformat():
                        entries.setdefault(entry["date"], entry)
                if (
                    missing.issubset(entries)
                    or index[-1]["date"] < begin.isoformat()
                    or len(entries) == before
                ):
                    break
            wanted = [entries[day] for day in sorted(missing, reverse=True) if day in entries]
            for i, entry in enumerate(wanted):
                if d.job.get("cancel"):
                    break
                with d.state_lock:
                    d.job["progress"] = (
                        f"Official Charts archive: {i+1} of {len(wanted)} earlier weeks · {entry['date']}…"
                    )
                try:
                    batch = fetch(s, entry["url"], charts, ttl=7 * 86400)
                    batch = [
                        {**row, "listingUrl": entry["url"]}
                        for row in batch
                        if row["releaseDate"] == entry["date"]
                    ]
                    if not batch:
                        raise ValueError(
                            "Official Charts archive page did not contain the expected dated release list: "
                            + entry["date"]
                        )
                    all_rows.extend(batch)
                    imported.add(entry["date"])
                    if on_batch:
                        on_batch(batch)
                except ValueError as exc:
                    d.add_warning(str(exc))
        missing = expected - imported
        if coverage is not None:
            coverage.update(
                archiveWeeksExpected=len(expected),
                archiveWeeksImported=len(expected & imported),
                archiveMissingWeeks=sorted(missing),
            )
        if missing and not d.job.get("cancel"):
            d.add_warning(
                "UK release archive is partial: "
                + ", ".join(sorted(missing))
                + ". Cached results were kept; retry Check releases to fill these weeks."
            )
    if country != "GB":
        d.add_warning(
            "No dedicated "
            + country
            + " release-listing supplier is connected yet. AllMusic listings are international editorial picks; availability in "
            + country
            + " is unverified."
        )
    merged = {}
    for row in all_rows:
        ident = key(s, row["artist"], row["album"])
        if ident not in merged:
            merged[ident] = {
                **row,
                "sources": [{"name": row["source"], "url": row["url"]}],
            }
        else:
            old = merged[ident]
            old["genres"] = list(dict.fromkeys(old["genres"] + row["genres"]))
            old["sources"].append({"name": row["source"], "url": row["url"]})
            for field in ("artwork", "label", "ratings", "reviewAuthor"):
                if row.get(field):
                    old[field] = row[field]
    return list(merged.values())


def apple_rows(text):
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ValueError("Invalid Apple catalogue response.")
    return data["results"]


def artist_albums(s, name, country):
    url = APPLE + urlencode(
        {
            "term": name,
            "country": country.lower(),
            "media": "music",
            "entity": "album",
            "attribute": "artistTerm",
            "limit": 200,
        }
    )
    rows = fetch(s, url, apple_rows, ttl=7 * 86400)
    exact = [
        r
        for r in rows
        if r.get("wrapperType") == "collection" and s.norm(r.get("artistName", "")) == s.norm(name)
    ]
    identities = {r.get("artistId") for r in exact if r.get("artistId")}
    if len(identities) > 1:
        d.add_warning(
            "Apple returned multiple artists named "
            + name
            + ". Those artist-catalogue results were skipped rather than guessing."
        )
        return []
    if len(rows) >= 200:
        d.add_warning(
            name
            + ": Apple results reached the 200-item limit; this discography check may be incomplete."
        )
    result = []
    for row in exact:
        title = row.get("collectionName", "")
        day = str(row.get("releaseDate", ""))[:10]
        if not title:
            continue
        typ = (
            "EP"
            if re.search(r"\s[-–] EP$", title, re.I)
            else "Single" if re.search(r"\s[-–] Single$", title, re.I) else "Album"
        )
        result.append(
            {
                "artist": row["artistName"],
                "album": title,
                "releaseDate": day,
                "releaseType": typ,
                "genres": genres.extract(row),
                "source": "Apple iTunes catalogue",
                "url": safe_url(row.get("collectionViewUrl", ""), "music.apple.com")
                or safe_url(row.get("collectionViewUrl", ""), "itunes.apple.com"),
                "market": country,
                "dateBasis": "catalogue-date",
                "appleArtistId": row.get("artistId"),
                "artwork": showcase.image_url(
                    re.sub(r"/\d+x\d+bb\.", "/600x600bb.", row.get("artworkUrl100", ""))
                ),
                "artworkSource": "Apple Music",
                "artworkSourceUrl": row.get("collectionViewUrl", ""),
            }
        )
    return result


def save(s, n, row, section, options, names):
    begin, end = n.window(options["days"])
    if row["releaseType"] not in n.TYPES[options["type"]] or not n.in_window(
        row["releaseDate"], begin, end
    ):
        return False
    names_by_norm = {s.norm(name): name for name in names}
    # Editorial slash-separated collaborations are also allowed; names are not guessed from substrings.
    credits = [row["artist"], *re.split(r"\s*/\s*", row["artist"])]
    matched = [names_by_norm[s.norm(name)] for name in credits if s.norm(name) in names_by_norm]
    if section == "library" and not matched:
        return False
    ident = hashlib.sha256(key(s, row["artist"], row["album"]).encode()).hexdigest()[:32]
    item = {
        "id": n.KINDS[section] + ":external:" + options["country"] + ":" + ident,
        "kind": n.KINDS[section],
        "provider": "independent",
        "artist": row["artist"],
        "album": row["album"],
        "releaseDate": row["releaseDate"],
        "originalDate": "",
        "releaseType": row["releaseType"],
        "genres": row["genres"],
        "source": row["source"],
        "sources": row.get("sources", [{"name": row["source"], "url": row["url"]}]),
        "artwork": showcase.image_url(row.get("artwork", "")),
        "artworkSource": row.get("artworkSource", "Publisher"),
        "artworkSourceUrl": row.get("artworkSourceUrl", ""),
        "label": row.get("label", ""),
        "ratings": row.get("ratings", []),
        "reviewAuthor": row.get("reviewAuthor", ""),
        "url": row["url"],
        "country": options["country"],
        "eventCountry": (
            options["country"] if row["market"] == options["country"] else "UNVERIFIED"
        ),
        "marketVerified": row["market"] == options["country"],
        "dateBasis": row["dateBasis"],
        "classification": "original-date-unconfirmed",
        "matchedArtists": matched,
        "reason": (
            "Listed for " + options["country"]
            if row["market"] == options["country"]
            else "International release listing; local availability unverified"
        )
        + " · "
        + row["source"],
    }
    if section == "library":
        item["reason"] = (
            "New release listing for "
            + ", ".join(matched)
            + " from your library · "
            + row["source"]
        )
    n.store(s, item)
    return True


def check(s, n, section, options, check, resume=False):
    names = n.library_artists(s) if section == "library" else []
    old_artist_hash = check.get("artistHash")
    if old_artist_hash and old_artist_hash != n.artist_hash(names):
        resume = False
    check.update(
        provider="independent",
        artistHash=n.artist_hash(names),
        totalArtists=len(names),
        checkedArtists=0,
        complete=False,
        hasMore=False,
    )
    if options.get("artistLookup"):
        offset = check.get("artistOffset", 0) if resume else 0
        batch = names[offset : offset + 10]
        found = 0
        for i, name in enumerate(batch):
            if n.stopped(s):
                return
            with d.state_lock:
                d.job["progress"] = (
                    f"Apple artist catalogues: {offset+i} of {len(names)} checked; results appear as they arrive…"
                )
            try:
                for row in artist_albums(s, name, options["country"]):
                    found += save(s, n, row, section, options, names)
            except ValueError as exc:
                if n.stopped(s):
                    return
                d.add_warning(str(exc))
                check.update(artistOffset=offset + i, hasMore=True)
                break
        else:
            check.update(
                artistOffset=offset + len(batch),
                hasMore=offset + len(batch) < len(names),
            )
        check.update(
            checkedArtists=check["artistOffset"],
            found=found,
            complete=not check["hasMore"],
            summary=f"Apple artist catalogues: {check['artistOffset']} of {len(names)} checked. Each action checks up to 10; repeat to continue. Cached checks are reused for seven days.",
        )
    else:
        begin, end = n.window(options["days"])

        def publish(batch):
            for row in batch:
                if n.stopped(s):
                    break
                save(s, n, row, section, options, names)

        rows = listings(
            s,
            options["country"],
            options["worldwide"] if section == "country" else True,
            begin,
            end,
            publish,
            check,
        )
        if n.stopped(s):
            return
        found = sum(save(s, n, row, section, options, names) for row in rows)
        check.update(
            complete=bool(rows) and not check.get("archiveMissingWeeks"),
            found=found,
            checkedArtists=len(names),
            summary=f"{len(rows)} published release listings checked"
            + (
                f" against all {len(names)} library artists locally."
                if section == "library"
                else ". No library artist scan was used."
            ),
        )
        if check.get("archiveWeeksExpected"):
            check[
                "summary"
            ] += f" UK weekly archive: {check['archiveWeeksImported']} of {check['archiveWeeksExpected']} weeks loaded."
        if not rows:
            d.add_warning(
                "No supplier returned usable release listings. Existing cached results have been kept."
            )
        # Coverage belongs in the page note; warnings are reserved for actual missing weeks or source failures.
