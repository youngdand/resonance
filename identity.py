"""Exact Unicode identities; loose edition matching belongs only in ownership hints."""

import re, unicodedata, hashlib


def normalize(value):
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    return " ".join("".join(c if c.isalnum() else " " for c in text).split())


def release_key(artist, album):
    a = normalize(artist)
    b = normalize(album)
    if not a or not b:
        raise ValueError("A release requires a nonempty artist and album identity.")
    return a + "|" + b


def external_id(kind, country, artist, album):
    return (
        kind
        + ":external:"
        + country
        + ":"
        + hashlib.sha256(release_key(artist, album).encode()).hexdigest()[:32]
    )


def migrate(s):
    import json

    with s.db() as c:
        c.execute("BEGIN IMMEDIATE")
        rows = c.execute(
            "SELECT id,value FROM discovery_items WHERE id LIKE '%:external:%'"
        ).fetchall()
        for row in rows:
            item = json.loads(row["value"])
            try:
                new = external_id(
                    item["kind"],
                    item.get("country", "GB"),
                    item["artist"],
                    item["album"],
                )
            except (ValueError, KeyError):
                continue
            old = row["id"]
            if old == new:
                continue
            existing = c.execute("SELECT value FROM discovery_items WHERE id=?", (new,)).fetchone()
            if existing:
                from metadata_store import merge

                item = merge(json.loads(existing[0]), item)
            item["id"] = new
            c.execute(
                "INSERT OR REPLACE INTO discovery_items VALUES (?,?)",
                (new, json.dumps(item)),
            )
            feedback = c.execute(
                "SELECT status FROM discovery_feedback WHERE id=?", (old,)
            ).fetchone()
            if feedback:
                current = c.execute(
                    "SELECT status FROM discovery_feedback WHERE id=?", (new,)
                ).fetchone()
                if not current or feedback[0] == "saved":
                    c.execute(
                        "INSERT OR REPLACE INTO discovery_feedback VALUES (?,?)",
                        (new, feedback[0]),
                    )
                c.execute("DELETE FROM discovery_feedback WHERE id=?", (old,))
            c.execute("INSERT OR REPLACE INTO release_aliases VALUES (?,?)", (old, new))
            c.execute("DELETE FROM discovery_items WHERE id=?", (old,))


def resolve(s, ident):
    with s.db() as c:
        row = c.execute("SELECT new_id FROM release_aliases WHERE old_id=?", (ident,)).fetchone()
    return row[0] if row else ident
