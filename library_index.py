"""One immutable matching index per completed library revision."""

import threading, re

lock = threading.RLock()
cached = None


def get(s):
    global cached
    with s.db() as c:
        revision = c.execute("SELECT revision FROM library_revision WHERE id=1").fetchone()[0]
    key = (str(s.DATA.resolve()), revision)
    with lock:
        if cached and cached["key"] == key:
            return cached
        with s.db() as c:
            c.execute("BEGIN")
            rows = [dict(r) for r in c.execute("SELECT * FROM tracks")]
            revision = c.execute("SELECT revision FROM library_revision WHERE id=1").fetchone()[0]
        titles = {}
        exact = set()
        loose = set()
        artists = set()
        profiles = {}
        for row in rows:
            a = s.norm(row["artist"])
            b = s.norm(row["album"])
            artists.add(a)
            exact.add((a, b))
            l = s.norm(
                re.sub(
                    r"\s*[\[(](?:deluxe|expanded|remaster(?:ed)?|anniversary|special edition)[^\])]*[\])]",
                    "",
                    row["album"],
                    flags=re.I,
                )
            )
            loose.add((a, l))
            titles.setdefault(s.norm(row["title"]), []).append(row)
            if not a or a in (
                "unknown",
                "unknown artist",
                "various artists",
                "various",
                "va",
            ):
                continue
            p = profiles.setdefault(
                row["artist"], {"artist": row["artist"], "albums": set(), "tracks": 0}
            )
            p["albums"].add(row["album"])
            p["tracks"] += 1
        profile = [{**p, "albums": sorted(p["albums"])} for p in profiles.values()]
        profile.sort(key=lambda a: (-len(a["albums"]), a["artist"].casefold()))
        cached = {
            "key": (str(s.DATA.resolve()), revision),
            "titles": titles,
            "artists": artists,
            "exact": exact,
            "loose": loose,
            "profile": profile,
            "tracks": len(rows),
        }
        return cached
