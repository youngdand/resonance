"""Safe, attributed release metadata. Never synthesize review scores or full reviews."""

from html.parser import HTMLParser
from urllib.parse import urlsplit
import json, re

IMAGE_HOSTS = (
    "mzstatic.com",
    "allmusic.com",
    "coverartarchive.org",
    "archive.org",
    "officialcharts.com",
    "officialcharts.co.uk",
    "dzcdn.net",
)


def image_url(value):
    if isinstance(value, list):
        return next((u for v in value if (u := image_url(v))), "")
    if isinstance(value, dict):
        return image_url(value.get("url") or value.get("contentUrl") or value.get("@id"))
    if not isinstance(value, str):
        return ""
    if value.startswith("//"):
        value = "https:" + value
    try:
        u = urlsplit(value)
        host = (u.hostname or "").lower()
        port = u.port
    except ValueError:
        return ""
    return (
        value
        if u.scheme == "https"
        and not u.username
        and port in (None, 443)
        and any(host == h or host.endswith("." + h) for h in IMAGE_HOSTS)
        and not any(
            x in value.lower()
            for x in ("no_image", "noimage", "placeholder", "default-cover", "no-cover")
        )
        else ""
    )


def image_attrs(attrs):
    for key in ("src", "data-src", "data-lazy-src", "data-original"):
        if image := image_url(attrs.get(key)):
            return image
    for key in ("srcset", "data-srcset"):
        for entry in reversed(str(attrs.get(key, "")).split(",")):
            if entry.strip() and (image := image_url(entry.strip().split()[0])):
                return image
    return ""


def public_link(value):
    if not isinstance(value, str):
        return ""
    u = urlsplit(value)
    return (
        value
        if u.scheme == "https"
        and not u.username
        and u.hostname
        in (
            "www.allmusic.com",
            "www.officialcharts.com",
            "music.apple.com",
            "itunes.apple.com",
            "musicbrainz.org",
            "pitchfork.com",
            "www.nme.com",
            "www.theguardian.com",
            "www.indieisnotagenre.com",
            "www.rollingstone.com",
            "www.nocleansinging.com",
            "www.silentradio.co.uk",
            "www.clashmusic.com",
            "thequietus.com",
        )
        else ""
    )


class Metadata(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self.json = []
        self.script = False
        self.buffer = ""
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            self.meta[a.get("property") or a.get("name", "")] = a.get("content", "")
        if tag == "script" and a.get("type") == "application/ld+json":
            self.script = True
            self.buffer = ""

    def handle_data(self, data):
        if self.script:
            self.buffer += data

    def handle_endtag(self, tag):
        if tag == "script" and self.script:
            try:
                self.json.append(json.loads(self.buffer))
            except (ValueError, TypeError):
                pass
            self.script = False

    def objects(self):
        def walk(value):
            if isinstance(value, dict):
                yield value
                for v in value.values():
                    yield from walk(v)
            elif isinstance(value, list):
                for v in value:
                    yield from walk(v)

        for obj in self.json:
            yield from walk(obj)


def score(value, publisher, url):
    if not isinstance(value, dict):
        return None
    try:
        rating = float(value["ratingValue"])
        best = float(value["bestRating"])
        if not 0 <= rating <= best or best <= 0 or best > 100:
            return None
    except (TypeError, ValueError, KeyError):
        return None
    return {
        "publisher": publisher,
        "value": rating,
        "best": best,
        "url": public_link(url),
        "kind": "critic",
    }


def author_name(value):
    if isinstance(value, dict):
        return str(value.get("name", ""))[:160]
    if isinstance(value, list):
        return ", ".join(author_name(v) for v in value)[:160]
    return str(value or "")[:160]


def album_metadata(text):
    result = {}
    for obj in Metadata(text).objects():
        if obj.get("@type") != "MusicAlbum":
            continue
        url = public_link(obj.get("url", ""))
        if not url:
            continue
        review = obj.get("review") or {}
        if isinstance(review, list):
            review = next((r for r in review if isinstance(r, dict)), {})
        if not isinstance(review, dict):
            review = {}
        entry = {
            "artwork": image_url(obj.get("image", "")),
            "label": (
                str(obj.get("recordLabel", ""))[:160]
                if isinstance(obj.get("recordLabel", ""), str)
                else author_name(obj.get("recordLabel"))
            ),
            "ratings": ([r] if (r := score(review.get("reviewRating"), "AllMusic", url)) else []),
            "reviewAuthor": author_name(review.get("author")),
        }
        previous = result.get(url.rstrip("/"), {})
        previous.update({k: v for k, v in entry.items() if v})
        result[url.rstrip("/")] = previous
    return result


def short_quote(text, limit=20):
    words = re.sub(r"\s+", " ", str(text or "")).strip().split()
    return " ".join(words[:limit]) + ("…" if len(words) > limit else "")


def overview(item):
    genre = ", ".join(item.get("genres", [])[:3])
    typ = item.get("releaseType", "release").lower()
    intro = f"{item.get('album','This release')} is {'an' if typ[:1] in 'aeiou' else 'a'} {typ} by {item.get('artist','the artist')}."
    if genre:
        intro += " Filed under " + genre + " in the publisher’s listing."
    context = (
        "It connects to an artist in your indexed collection."
        if item.get("matchedArtists")
        else "It is part of the release listings for this discovery view."
    )
    if item.get("label"):
        context += " Listed label: " + item["label"] + "."
    return intro + " " + context
