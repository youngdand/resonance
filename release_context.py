"""Find album-specific release notes in the dated Official Charts feature."""

from datetime import date
import review_sources as reviews
import release_sources


def lookup(s, item):
    sources = item.get("sources") or [{"url": item.get("url", "")}]
    if not any("www.officialcharts.com/" in x.get("url", "") for x in sources):
        return []
    try:
        day = date.fromisoformat(item["releaseDate"])
    except (KeyError, TypeError, ValueError):
        return []
    months = (
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    )
    url = f"https://www.officialcharts.com/chart-news/new-music-friday-{months[day.month-1]}-{day.day}-{day.year}/"
    reviews.init(s)

    def load():
        tree = release_sources.Tree(reviews.fetch(url, s.diag.VERSION)).root
        paragraphs = [p.text for p in tree.all("p") if len(p.text.split()) >= 20]
        return {"rows": paragraphs, "status": "Release feature checked"}

    record = reviews.cached(s, "context-v1:" + url, load, 7 * 86400)
    paragraph = next(
        (
            p
            for p in record.get("rows", [])
            if reviews.phrase(item["artist"], p) and reviews.phrase(item["album"], p)
        ),
        "",
    )
    if not paragraph:
        return []
    return [
        {
            "publisher": "Official Charts",
            "url": url,
            "title": "About " + item["album"],
            "excerpt": reviews.preview(paragraph),
            "author": "Official Charts",
            "published": day.isoformat(),
            "kind": "release-note",
            "review": False,
            "ratings": [],
            "tracks": [],
            "stale": record.get("stale", False),
        }
    ]
