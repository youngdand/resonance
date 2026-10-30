"""Date-filtered library-artist and country release feeds; no location tracking."""

from datetime import date, timedelta
from urllib.parse import urlencode
import hashlib, json, threading, time, sys
import discovery as d
import release_genres as g
import release_sources
import showcase_data
import release_details
import review_sources
import release_artwork
from features import store_settings

COUNTRIES = "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW".split()
TYPES = {
    "albums": ("Album", "EP"),
    "singles": ("Single",),
    "eps": ("EP",),
    "all": ("Album", "EP", "Single"),
}
KINDS = {"library": "new-library-release", "country": "new-country-release"}


def init(s):
    d.init(s)
    import storage

    storage.ensure_schema(
        s,
        "release_checks",
        "CREATE TABLE IF NOT EXISTS discovery_release_checks (key TEXT PRIMARY KEY, value TEXT)",
    )


def preferences(s):
    saved = s.settings(True)
    return {
        "country": saved.get("releaseCountry", "GB"),
        "days": saved.get("releaseDays", 30),
        "type": saved.get("releaseType", "albums"),
        "worldwide": saved.get("releaseWorldwide", True),
        "includeOlder": saved.get("releaseIncludeOlder", False),
        "genre": saved.get("releaseGenre", "all"),
        "sort": saved.get("releaseSort", "recent"),
        "focus": saved.get("releaseFocus", "all"),
        "q": "",
    }


def filters(s, body):
    values = {
        **preferences(s),
        **{
            k: body[k]
            for k in (
                "country",
                "days",
                "type",
                "worldwide",
                "includeOlder",
                "genre",
                "sort",
                "focus",
                "q",
            )
            if k in body
        },
    }
    values["country"] = str(values["country"]).upper()
    if values["country"] not in COUNTRIES:
        raise ValueError("Choose a valid release country.")
    if isinstance(values["days"], bool):
        raise ValueError("Choose a valid date window.")
    try:
        values["days"] = int(values["days"])
    except (ValueError, TypeError):
        raise ValueError("Choose a valid date window.") from None
    if values["days"] not in (7, 30, 90):
        raise ValueError("Choose the last 7, 30 or 90 days.")
    if values["type"] not in TYPES:
        raise ValueError("Choose a valid release type.")
    if not isinstance(values["worldwide"], bool) or not isinstance(values["includeOlder"], bool):
        raise ValueError("Invalid release filter.")
    if values["genre"] not in ("all", "unclassified", *g.GENRES):
        raise ValueError("Choose a valid genre.")
    if values["sort"] not in ("recent", "artist", "rating"):
        raise ValueError("Invalid release ordering.")
    if values["focus"] not in ("all", "saved", "reviewed", "new"):
        raise ValueError("Invalid discovery focus.")
    if not isinstance(values["q"], str) or len(values["q"]) > 200:
        raise ValueError("Search must be 200 characters or fewer.")
    return values


def window(days, today=None):
    today = today or date.today()
    return today - timedelta(days=days - 1), today


def exact_date(value):
    try:
        return date.fromisoformat(str(value)) if len(str(value)) == 10 else None
    except ValueError:
        return None


def in_window(value, begin, end):
    parsed = exact_date(value)
    return parsed is not None and begin <= parsed <= end


def feed_key(section, options):
    fields = [
        section,
        options["days"],
        options["type"],
        options.get("provider", "independent"),
        bool(options.get("artistLookup")),
    ]
    fields += [options["country"]]
    if section == "country":
        fields += [options["worldwide"]]
    return json.dumps(fields, separators=(",", ":"))


def library_artists(s):
    names = {}
    for row in d.profile(s):
        # Our tag reader joins multiple performers with semicolons; do not split band names on & or commas.
        for name in row["artist"].split(";"):
            name = name.strip()
            if name and s.norm(name) not in (
                "unknown",
                "unknown artist",
                "various artists",
                "various",
                "va",
            ):
                names.setdefault(s.norm(name), name)
    return sorted(names.values(), key=str.casefold)


def artist_hash(names):
    return hashlib.sha256(json.dumps(names, ensure_ascii=False).encode()).hexdigest()


def stopped(s):
    return d.job.get("cancel") or not s.settings(True).get("discoveryOnline", False)


def request(s, entity, params):
    if stopped(s):
        raise ValueError("Discovery stopped.")
    return d.cached_json(
        s, d.MB + entity + "?" + urlencode({**params, "fmt": "json"}), max_age=3600
    )


def error(exc):
    if isinstance(exc, d.CatalogueUnavailable):
        d.diag.event("release-service-unavailable", "WARNING", service=exc.host)
    else:
        d.diag.error(exc, operation="new-releases")
    with d.state_lock:
        if str(exc) not in d.job["errors"]:
            d.job["errors"].append(str(exc))


def credits(record):
    return [
        c["artist"]
        for c in record.get("artist-credit", [])
        if isinstance(c, dict) and isinstance(c.get("artist"), dict)
    ]


def artist_label(record):
    parts = []
    for c in record.get("artist-credit", []):
        if isinstance(c, dict):
            parts.append(
                (c.get("name") or c.get("artist", {}).get("name", "")) + c.get("joinphrase", "")
            )
    return "".join(parts) or "Unknown artist"


def store(s, item):
    with s.db() as c:
        old = c.execute("SELECT value FROM discovery_items WHERE id=?", (item["id"],)).fetchone()
    if item["kind"] == KINDS["country"]:
        previous = json.loads(old[0]) if old else {}
        events = dict(previous.get("events", {}))
        code = item["eventCountry"]
        events[code] = max(events.get(code, ""), item["releaseDate"])
        item["events"] = events
        if not item.get("originalDate") and previous.get("originalDate"):
            item["originalDate"] = previous["originalDate"]
    elif old:
        previous = json.loads(old[0])
        if previous.get("releaseDate", "") > item["releaseDate"]:
            return
        item["matchedArtists"] = list(
            dict.fromkeys(previous.get("matchedArtists", []) + item.get("matchedArtists", []))
        )
        item["matchedArtistIds"] = {
            **previous.get("matchedArtistIds", {}),
            **item.get("matchedArtistIds", {}),
        }
    if old and not item.get("genres"):
        item["genres"] = json.loads(old[0]).get("genres", [])
    if old:
        previous = json.loads(old[0])
        if not item.get("artwork"):
            for field in ("artwork", "artworkSource", "artworkSourceUrl"):
                if previous.get(field):
                    item[field] = previous[field]
        elif item.get("artwork") == previous.get("artwork"):
            for field in ("artworkSource", "artworkSourceUrl"):
                if previous.get(field):
                    item[field] = previous[field]
        if not item.get("coveragePreview") and previous.get("coveragePreview"):
            item["coveragePreview"] = previous["coveragePreview"]
    d.add(s, item)


def base_item(group, kind, release_date):
    ident = d.valid_id(group["id"])
    return {
        "kind": kind,
        "mbid": ident,
        "artist": artist_label(group),
        "artistMbid": credits(group)[0].get("id", "") if credits(group) else "",
        "album": group.get("title", "Untitled release"),
        "year": release_date[:4],
        "releaseDate": release_date,
        "originalDate": group.get("first-release-date", ""),
        "genres": g.extract(group),
        "releaseType": group.get("primary-type", "Other"),
        "secondaryTypes": group.get("secondary-types", []),
        "source": "MusicBrainz release catalogue",
        "url": "https://musicbrainz.org/release-group/" + ident,
    }


def chunks(items, size=20, max_length=1400):
    batch = []
    length = 0
    for item in items:
        weight = len(urlencode({"value": str(item)}))
        if batch and (len(batch) >= size or length + weight > max_length):
            yield batch
            batch = []
            length = 0
        batch.append(item)
        length += weight
    if batch:
        yield batch


def library_check(s, options, check):
    begin, end = window(options["days"])
    names = library_artists(s)
    check.update(totalArtists=len(names), artistHash=artist_hash(names), checkedArtists=0)
    with s.db() as c:
        known = {
            r["artist"]: r["mbid"] for r in c.execute("SELECT artist,mbid FROM discovery_matches")
        }
    resolved = {}
    seen = set()
    matched = set()
    types = TYPES[options["type"]]
    for batch in chunks(names):
        if stopped(s):
            return
        terms = [
            (
                "arid:" + d.valid_id(known[s.norm(name)])
                if s.norm(name) in known
                else "artistname:" + d.literal(name)
            )
            for name in batch
        ]
        query = (
            "("
            + " OR ".join(terms)
            + ") AND firstreleasedate:["
            + begin.isoformat()
            + " TO "
            + end.isoformat()
            + "] AND ("
            + " OR ".join("primarytype:" + t.lower() for t in types)
            + ") AND status:official"
        )
        offset = 0
        while True:
            with d.state_lock:
                d.job["progress"] = (
                    f"Checking new releases: {check['checkedArtists']} of {len(names)} library artists checked…"
                )
            data = request(s, "release-group/", {"query": query, "limit": 100, "offset": offset})
            if not isinstance(data, dict) or not isinstance(data.get("release-groups"), list):
                raise ValueError(
                    "MusicBrainz did not return a release-group list. Existing releases have been kept."
                )
            rows = data["release-groups"]
            for group in rows:
                if stopped(s):
                    return
                if group.get("primary-type") not in types or not in_window(
                    group.get("first-release-date"), begin, end
                ):
                    continue
                artist_ids = {a.get("id") for a in credits(group)}
                credit_names = {s.norm(a.get("name", "")) for a in credits(group)}
                matches = []
                for name in batch:
                    norm = s.norm(name)
                    if norm in known:
                        if known[norm] in artist_ids:
                            matches.append(name)
                    elif norm in credit_names:
                        if norm not in resolved:
                            resolved[norm] = d.resolve(s, name)
                        identity = resolved[norm]
                        if identity and identity["mbid"] in artist_ids:
                            matches.append(name)
                if not matches:
                    continue
                item = base_item(group, KINDS["library"], group["first-release-date"])
                item.update(
                    id=KINDS["library"] + ":" + item["mbid"],
                    classification="new-release",
                    matchedArtists=matches,
                    matchedArtistIds={
                        n: known.get(s.norm(n)) or resolved[s.norm(n)]["mbid"] for n in matches
                    },
                    reason="New release from " + ", ".join(matches) + " in your library",
                )
                store(s, item)
                seen.add(item["id"])
                matched.update(matches)
            offset += len(rows)
            total = int(data.get("count", offset))
            if not rows and offset < total:
                check["limited"] = True
                d.add_warning(
                    "The catalogue returned an incomplete artist page. Some releases may be missing."
                )
                break
            if not rows or offset >= total:
                break
            if offset >= 2000:
                d.add_warning(
                    "A very large artist result set was limited to 2,000 catalogue groups per batch. Some releases may be missing."
                )
                check["limited"] = True
                break
        check["checkedArtists"] += len(batch)
        check.update(found=len(seen), matchedArtists=len(matched))
    check["ambiguousArtists"] = sum(1 for value in resolved.values() if value is None)
    check["complete"] = not check.get("limited") and not check["ambiguousArtists"]


def release_event(release, country, worldwide, begin, end):
    allowed = {country} | ({"XW"} if worldwide else set())
    matches = []
    events = release.get("release-events")
    if events:
        for event in events:
            codes = (event.get("area") or {}).get("iso-3166-1-codes", []) or []
            overlap = allowed.intersection(codes)
            if overlap and in_window(event.get("date"), begin, end):
                matches.append((event["date"], country if country in overlap else "XW"))
    elif release.get("country") in allowed and in_window(release.get("date"), begin, end):
        matches.append((release["date"], release["country"]))
    local = [m for m in matches if m[1] == country]
    return max(local or matches) if matches else None


def group_metadata(s, groups):
    result = {}
    missing = []
    for group in groups:
        ident = d.valid_id(group["id"])
        if group.get("first-release-date"):
            result[ident] = group
        else:
            missing.append(ident)
    for batch in chunks(list(dict.fromkeys(missing))):
        try:
            data = request(
                s,
                "release-group/",
                {
                    "query": "(" + " OR ".join("rgid:" + ident for ident in batch) + ")",
                    "limit": 100,
                },
            )
            for group in data.get("release-groups", []):
                result[d.valid_id(group["id"])] = group
        except d.CatalogueUnavailable as exc:
            # Country/date listings remain useful; never label unknown originals as newly recorded albums.
            error(exc)
            d.add_warning(
                "Some original release dates could not be verified. Those cards are labelled Original date unconfirmed."
            )
            break
    return result


def country_check(s, options, check, resume=False):
    begin, end = window(options["days"])
    offset = check.get("nextOffset", 0) if resume else 0
    query = (
        "("
        + (
            "country:" + options["country"] + " OR country:XW"
            if options["worldwide"]
            else "country:" + options["country"]
        )
        + ") AND date:["
        + begin.isoformat()
        + " TO "
        + end.isoformat()
        + "] AND ("
        + " OR ".join("primarytype:" + t.lower() for t in TYPES[options["type"]])
        + ") AND status:official"
    )
    seen = set()
    pages = 0
    while pages < 5 and not stopped(s):
        with d.state_lock:
            d.job["progress"] = (
                f"Checking {options['country']} release listings: {offset} editions checked…"
            )
        data = request(s, "release/", {"query": query, "limit": 100, "offset": offset})
        if not isinstance(data, dict) or not isinstance(data.get("releases"), list):
            raise ValueError(
                "MusicBrainz did not return a release list. Existing releases have been kept."
            )
        rows = data["releases"]
        check["sourceTotal"] = int(data.get("count", offset + len(rows)))
        if not rows and offset < check["sourceTotal"]:
            check.update(limited=True, complete=False, nextOffset=offset)
            d.add_warning(
                "The catalogue returned no further page before its reported total. Narrow the date window to search further; these results are partial."
            )
            break
        candidates = []
        for release in rows:
            if release.get("status", "Official").casefold() != "official":
                continue
            event = release_event(release, options["country"], options["worldwide"], begin, end)
            group = release.get("release-group") or {}
            if event and group.get("id"):
                candidates.append((release, event, group))
        metadata = group_metadata(s, [g for _, _, g in candidates])
        for release, event, raw_group in candidates:
            if stopped(s):
                return
            group = {**raw_group, **metadata.get(raw_group["id"], {})}
            group["genres"] = g.extract(group) or g.extract(release)
            if group.get("primary-type") not in TYPES[options["type"]]:
                continue
            if not group.get("artist-credit"):
                group["artist-credit"] = release.get("artist-credit", [])
            original = exact_date(group.get("first-release-date"))
            local = exact_date(event[0])
            classification = (
                "new-release"
                if original and begin <= original <= local
                else (
                    "catalogue-edition"
                    if original and original < begin
                    else "original-date-unconfirmed"
                )
            )
            item = base_item(group, KINDS["country"], event[0])
            item.update(
                id=KINDS["country"] + ":" + options["country"] + ":" + item["mbid"],
                country=options["country"],
                eventCountry=event[1],
                classification=classification,
                reason=(
                    "Worldwide catalogue release"
                    if event[1] == "XW"
                    else "Released in " + options["country"]
                )
                + " on "
                + event[0],
            )
            store(s, item)
            seen.add(item["id"])
        offset += len(rows)
        pages += 1
        check.update(
            nextOffset=offset,
            found=check.get("found", 0) + len(seen),
            complete=not rows or offset >= check["sourceTotal"],
        )
        seen.clear()
        if check["complete"]:
            break
    check["hasMore"] = not check.get("complete", False) and not check.get("limited", False)
    if check["hasMore"]:
        d.add_warning(
            f"Checked {offset} of {check['sourceTotal']} matching catalogue editions. Continue the check to search more."
        )


def run(s, section, options, resume):
    init(s)
    key = feed_key(section, options)
    begin, end = window(options["days"])
    previous = read_check(s, key)
    check = {**previous} if resume else {}
    check.pop("limited", None)
    check.update(
        section=section,
        options=options,
        fromDate=begin.isoformat(),
        toDate=end.isoformat(),
        complete=False,
        attemptedAt=time.time(),
    )
    try:
        if options.get("provider", "independent") == "independent":
            release_sources.check(s, sys.modules[__name__], section, options, check, resume)
        elif section == "library":
            library_check(s, options, check)
        else:
            country_check(s, options, check, resume)
        if not stopped(s):
            check["checkedAt"] = time.time()
    except Exception as exc:
        if not stopped(s):
            error(exc)
    finally:
        check["cancelled"] = bool(stopped(s))
        check["partial"] = bool(d.job["errors"]) or not check.get("complete", False)
        if d.job["errors"]:
            check["complete"] = False
        if section == "country":
            check["hasMore"] = (
                not check.get("complete", False)
                and not check.get("limited", False)
                and check.get("nextOffset", 0) < check.get("sourceTotal", 0)
            )
        try:
            with s.db() as c:
                c.execute(
                    "INSERT OR REPLACE INTO discovery_release_checks VALUES (?,?)",
                    (key, json.dumps(check)),
                )
        except Exception as exc:
            error(exc)
        finally:
            with d.state_lock:
                d.job.update(
                    running=False,
                    updated=time.time(),
                    progress=(
                        "Stopped"
                        if check["cancelled"]
                        else (
                            "Release check complete"
                            if check["complete"] and not d.job["errors"]
                            else "Release check finished with partial results"
                        )
                    ),
                )


def read_check(s, key):
    with s.db() as c:
        row = c.execute("SELECT value FROM discovery_release_checks WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else {}


def start(s, body):
    init(s)
    if not s.settings(True).get("discoveryOnline", False):
        raise ValueError("Enable online discovery before checking for releases.")
    section = body.get("section", "library")
    if section not in KINDS:
        raise ValueError("Choose a valid release tab.")
    options = filters(s, body)
    options["provider"] = body.get("provider", "independent")
    if options["provider"] not in ("independent", "musicbrainz"):
        raise ValueError("Invalid release provider.")
    options["artistLookup"] = body.get("artistLookup") is True and section == "library"
    if section == "library" and not library_artists(s):
        raise ValueError("Scan your music library first. Artist tags are needed for this tab.")
    previous = read_check(s, feed_key(section, options))
    begin, end = window(options["days"])
    resume = (
        body.get("continue") is True
        and (section == "country" or options["artistLookup"])
        and previous.get("toDate") == end.isoformat()
        and previous.get("hasMore", False)
    )
    with d.state_lock:
        if d.job["running"]:
            return {
                "running": True,
                "kind": d.job.get("kind", "related"),
                "alreadyRunning": True,
            }
        d.job.update(
            running=True,
            errors=[],
            warnings=[],
            retryAt=0,
            candidates=[],
            cancel=False,
            kind="releases-" + section,
            progress="Checking recent releases…",
        )
    threading.Thread(target=run, args=(s, section, options, resume), daemon=True).start()
    return {"running": True, "kind": "releases-" + section}


def snapshot(s, body):
    init(s)
    section = body.get("section", "library")
    if section not in KINDS:
        raise ValueError("Choose a valid release tab.")
    options = filters(s, body)
    begin, end = window(options["days"])
    names = library_artists(s)
    with s.db() as c:
        raw = [json.loads(r[0]) for r in c.execute("SELECT value FROM discovery_items")]
        feedback = {r["id"]: r["status"] for r in c.execute("SELECT * FROM discovery_feedback")}
        matches = {
            r["artist"]: r["mbid"] for r in c.execute("SELECT artist,mbid FROM discovery_matches")
        }
    rows = []
    name_set = {s.norm(n) for n in names}
    for item in raw:
        if item.get("kind") != KINDS[section]:
            continue
        if item.get("releaseType") not in TYPES[options["type"]]:
            continue
        if section == "country":
            if item.get("country") != options["country"]:
                continue
            events = item.get("events") or {item.get("eventCountry"): item["releaseDate"]}
            allowed = [
                (day, code)
                for code, day in events.items()
                if (
                    code == options["country"]
                    or code in ("XW", "UNVERIFIED")
                    and options["worldwide"]
                )
                and in_window(day, begin, end)
            ]
            if not allowed:
                continue
            local = [e for e in allowed if e[1] == options["country"]]
            day, code = max(local or allowed)
            item.update(
                releaseDate=day,
                eventCountry=code,
                reasons=(
                    item.get("reasons", [])
                    if item.get("provider") == "independent"
                    else [
                        ("Worldwide catalogue release" if code == "XW" else "Released in " + code)
                        + " on "
                        + day
                    ]
                ),
            )
            original = exact_date(item.get("originalDate"))
            event_date = exact_date(day)
            item["classification"] = (
                "new-release"
                if original and begin <= original <= event_date
                else (
                    "catalogue-edition"
                    if original and original < begin
                    else "original-date-unconfirmed"
                )
            )
            if not options["includeOlder"] and item["classification"] == "catalogue-edition":
                continue
        else:
            if not in_window(item.get("releaseDate"), begin, end):
                continue
            if not any(
                s.norm(n) in name_set
                and (
                    not item.get("matchedArtistIds")
                    or matches.get(s.norm(n)) == item["matchedArtistIds"].get(n)
                )
                for n in item.get("matchedArtists", [])
            ):
                continue
        item["feedback"] = feedback.get(item["id"], "")
        item["libraryStatus"] = d.ownership(s, item["artist"], item.get("album"))
        if item["feedback"] != "dismissed":
            rows.append(item)
    words = s.norm(options["q"]).split()
    if words:
        rows = [
            item
            for item in rows
            if all(
                word
                in s.norm(
                    " ".join(
                        [
                            item.get("artist", ""),
                            item.get("album", ""),
                            item.get("label", ""),
                            *item.get("genres", []),
                        ]
                    )
                )
                for word in words
            )
        ]
    if options["focus"] == "saved":
        rows = [item for item in rows if item.get("feedback") == "saved"]
    elif options["focus"] == "reviewed":
        rows = [item for item in rows if item.get("ratings")]
    elif options["focus"] == "new":
        rows = [
            item
            for item in rows
            if item.get("libraryStatus") not in ("album-in-library", "possible-album")
        ]
    for item in rows:
        item["overview"] = showcase_data.overview(item)
    available = {genre: 0 for genre in g.GENRES}
    unclassified = 0
    for item in rows:
        item["genres"], item["genreCategories"] = g.normalized(item)
        for genre in item["genreCategories"]:
            available[genre] += 1
        if not item["genreCategories"]:
            unclassified += 1
    unfiltered_total = len(rows)
    if options["genre"] == "unclassified":
        rows = [item for item in rows if not item["genreCategories"]]
    elif options["genre"] != "all":
        rows = [item for item in rows if options["genre"] in item["genreCategories"]]
    rows.sort(
        key=lambda i: (i["releaseDate"], i["album"].casefold(), i["artist"].casefold()),
        reverse=True,
    )
    if options["sort"] == "artist":
        rows.sort(key=lambda i: (i["artist"].casefold(), i["album"].casefold()))
    elif options["sort"] == "rating":
        rows.sort(
            key=lambda i: max(
                (
                    r.get("value", 0) / r["best"]
                    for r in i.get("ratings", [])
                    if r.get("best", 0) > 0
                ),
                default=-1,
            ),
            reverse=True,
        )
    try:
        offset = max(0, int(body.get("offset", 0)))
        limit = min(100, max(1, int(body.get("limit", 48))))
    except (TypeError, ValueError):
        raise ValueError("Invalid release page.") from None
    check = read_check(s, feed_key(section, options))
    changed = section == "library" and check.get("artistHash") != artist_hash(names)
    return {
        "items": rows[offset : offset + limit],
        "total": len(rows),
        "offset": offset,
        "hasMore": offset + limit < len(rows),
        "check": check,
        "options": options,
        "countries": COUNTRIES,
        "genreCounts": available,
        "unclassified": unclassified,
        "unfilteredTotal": unfiltered_total,
        "libraryArtists": len(names),
        "artistCheck": (
            read_check(s, feed_key(section, {**options, "artistLookup": True}))
            if section == "library"
            else {}
        ),
        "libraryChanged": changed,
        "fromDate": begin.isoformat(),
        "toDate": end.isoformat(),
    }


def get_route(h, path, q, s):
    if path == "/api/discovery/releases/artwork":
        h.send_json(
            release_artwork.find(
                s,
                __import__("identity").resolve(s, q.get("id", [""])[0]),
                q.get("failed", [""])[0],
            )
        )
        return True
    if path == "/api/discovery/releases/reviews":
        h.send_json(
            review_sources.for_release(s, __import__("identity").resolve(s, q.get("id", [""])[0]))
        )
        return True
    if path == "/api/discovery/releases/detail":
        h.send_json(
            release_details.dossier(s, __import__("identity").resolve(s, q.get("id", [""])[0]))
        )
        return True
    if path != "/api/discovery/releases":
        return False
    body = {k: v[0] for k, v in q.items()}
    for k in ("worldwide", "includeOlder"):
        if k in body:
            body[k] = body[k] == "true"
    h.send_json(snapshot(s, body))
    return True


def post_route(h, path, body, s):
    if path == "/api/discovery/releases/start":
        h.send_json(start(s, body))
        return True
    if path == "/api/discovery/releases/preferences":
        options = filters(s, body)
        store_settings(
            s,
            {
                "releaseCountry": options["country"],
                "releaseDays": options["days"],
                "releaseType": options["type"],
                "releaseWorldwide": options["worldwide"],
                "releaseIncludeOlder": options["includeOlder"],
                "releaseGenre": options["genre"],
                "releaseSort": options["sort"],
                "releaseFocus": options["focus"],
            },
        )
        h.send_json(options)
        return True
    return False
