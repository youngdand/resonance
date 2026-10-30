"""Merge observed facts without erasing enrichment when listing fields are absent."""

import json

FIELDS = (
    "artwork",
    "artworkSource",
    "artworkSourceUrl",
    "coveragePreview",
    "genres",
    "label",
    "reviewAuthor",
)


def merge(previous, incoming):
    item = {**previous, **incoming}
    for name in FIELDS:
        if not incoming.get(name) and previous.get(name):
            item[name] = previous[name]
    if incoming.get("artwork") and incoming["artwork"] != previous.get("artwork"):
        item["artworkSource"] = incoming.get("artworkSource", "Publisher")
        item["artworkSourceUrl"] = incoming.get("artworkSourceUrl", "")
    scores = {(r.get("publisher"), r.get("url")): r for r in previous.get("ratings", [])}
    scores.update({(r.get("publisher"), r.get("url")): r for r in incoming.get("ratings", [])})
    if scores:
        item["ratings"] = list(scores.values())
    sources = {r.get("url"): r for r in previous.get("sources", []) if r.get("url")}
    sources.update({r.get("url"): r for r in incoming.get("sources", []) if r.get("url")})
    if sources:
        item["sources"] = list(sources.values())
    if previous.get("events") or incoming.get("events"):
        item["events"] = {**previous.get("events", {}), **incoming.get("events", {})}
    return item


def save(s, item):
    with s.db() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT value FROM discovery_items WHERE id=?", (item["id"],)).fetchone()
        value = merge(json.loads(row[0]), item) if row else dict(item)
        reason = value.pop("reason", None)
        reasons = list(value.get("reasons", []))
        if reason and reason not in reasons:
            reasons.append(reason)
        value["reasons"] = reasons[-8:]
        c.execute(
            "INSERT OR REPLACE INTO discovery_items VALUES (?,?)",
            (value["id"], json.dumps(value)),
        )
    return value
