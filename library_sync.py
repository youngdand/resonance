"""Import slskd's share inventory, enriching only changed local files with tags."""

from pathlib import Path, PureWindowsPath
import json, os, threading, time


def share_state(s):
    state = s.slsk("application").get("shares")
    if not isinstance(state, dict):
        raise ValueError(
            "slskd did not return its share scan status. Your previous collection has been kept."
        )
    return state


def wait_ready(s, refresh):
    state = share_state(s)
    if refresh and not state.get("scanning"):
        s.slsk("shares", "PUT")
        # Give the asynchronous scan time to publish its state, even for small shares.
        time.sleep(1)
    deadline = time.monotonic() + 900
    while True:
        state = share_state(s)
        s.scan_state.update(phase="slskd", progress=state.get("scanProgress", 0))
        if state.get("faulted") or state.get("cancelled"):
            raise ValueError(
                "slskd could not finish its share scan. Your previous collection has been kept; check its log."
            )
        if not state.get("scanning"):
            if not state.get("ready") or state.get("scanPending") and not state.get("errors"):
                raise ValueError(
                    "slskd shares are not ready. Finish its share scan, then refresh the collection."
                )
            if state.get("errors"):
                s.scan_state["warning"] = (
                    f"slskd retained previous entries for {state['errors']} unreadable paths. Check its log for details."
                )
            return
        if time.monotonic() > deadline:
            raise ValueError(
                "Still waiting for slskd after 15 minutes. Its scan may continue; your previous collection has been kept."
            )
        time.sleep(2)


def local_inventory(s):
    shares = s.slsk("shares")
    local = shares.get("local")
    if not isinstance(local, list):
        raise ValueError(
            "slskd did not return its local shares. Your previous collection has been kept."
        )
    mappings = []
    for share in local:
        if share.get("isExcluded"):
            continue
        root = share.get("localPath", "")
        remote = share.get("remotePath", share.get("alias", "")).replace("\\", "/").rstrip("/")
        if root and remote:
            mappings.append((remote, Path(root)))
    mappings.sort(key=lambda x: len(x[0]), reverse=True)
    contents = s.slsk("shares/contents")
    if not isinstance(contents, list):
        raise ValueError(
            "slskd returned an invalid share inventory. Your previous collection has been kept."
        )
    files = {}
    for directory in contents:
        name = directory.get("name", "").replace("\\", "/").rstrip("/")
        match = next(
            (
                (alias, root)
                for alias, root in mappings
                if name.casefold() == alias.casefold()
                or name.casefold().startswith(alias.casefold() + "/")
            ),
            None,
        )
        if not match:
            continue  # remote relay shares cannot be read on this computer
        alias, root = match
        relative = name[len(alias) :].strip("/")
        parts = relative.split("/") if relative else []
        if any(p in (".", "..") for p in parts):
            raise ValueError("An unsafe directory was returned in the share inventory.")
        for f in directory.get("files", []):
            filename = f.get("filename", "")
            if not filename or "/" in filename or "\\" in filename or filename in (".", ".."):
                raise ValueError("An invalid filename was returned in the share inventory.")
            if PureWindowsPath(filename).suffix.lower() not in s.AUDIO:
                continue
            path = root.joinpath(*parts, filename)
            # Resolve a junction to its actual file so E:\ and C:\SoulseekMusic do not duplicate tracks.
            canonical = os.path.normcase(os.path.realpath(path))
            files[canonical] = (path, root, f)
    return files, len(mappings)


def metadata_inventory(s):
    shares = s.slsk("shares").get("local", [])
    mappings = []
    for share in shares:
        if share.get("isExcluded"):
            continue
        alias = share.get("remotePath", share.get("alias", "")).replace("\\", "/").rstrip("/")
        if alias and share.get("localPath"):
            mappings.append((alias, os.path.normcase(os.path.realpath(share["localPath"]))))
    mappings.sort(key=lambda x: len(x[0]), reverse=True)
    after = ""
    revision = None
    tracks = {}
    while True:
        from urllib.parse import urlencode

        query = {"after": after, "limit": 1000}
        if revision is not None:
            query["revision"] = revision
        try:
            page = s.slsk("shares/library?" + urlencode(query))
        except ValueError as e:
            if not tracks and (
                getattr(e, "status", None) in (404, 405)
                or getattr(e, "code", None) == "library_metadata_missing"
            ):
                return None
            raise
        # Some older integrations return an empty object for unknown endpoints.
        if not isinstance(page, dict) or "items" not in page:
            if not tracks:
                return None
            raise ValueError(
                "slskd returned an incomplete music library page. Previous collection kept."
            )
        if not isinstance(page["items"], list) or not page.get("complete", False):
            raise ValueError("slskd music metadata is incomplete. Refresh its shares and retry.")
        if revision is not None and page.get("revision") != revision:
            raise ValueError(
                "slskd changed during the import. Refresh again; previous collection kept."
            )
        revision = page.get("revision")
        for item in page["items"]:
            f = item.get("file") or {}
            name = str(f.get("filename", "")).replace("\\", "/")
            if PureWindowsPath(name).suffix.lower() not in s.AUDIO:
                continue
            match = next(
                ((alias, path) for alias, path in mappings if name.startswith(alias + "/")),
                None,
            )
            if not match:
                continue
            alias, path = match
            parts = name[len(alias) + 1 :].split("/")
            if any(not x or x in (".", "..") or ":" in x for x in parts):
                raise ValueError("Unsafe path in slskd metadata inventory.")
            canonical = os.path.normcase(os.path.join(path, *parts))
            tracks[canonical] = (
                canonical,
                path,
                item.get("artist") or item.get("albumArtist") or "",
                item.get("album") or (parts[-2] if len(parts) > 1 else ""),
                item.get("title") or s.filename_title(parts[-1]),
                item.get("duration") or s.attr(f, "length", 1),
                PureWindowsPath(name).suffix[1:].lower(),
                f.get("size", 0),
            )
        s.scan_state.update(count=len(tracks), phase="metadata-cache", tagsRead=0)
        if not page.get("hasMore"):
            break
        cursor = page.get("after")
        if not cursor or cursor == after:
            raise ValueError("slskd returned a repeated library cursor. Previous collection kept.")
        after = cursor
    # A scan beginning after the last page must not publish a mixed inventory.
    state = share_state(s)
    if state.get("scanning") or not state.get("ready"):
        raise ValueError(
            "slskd began scanning during import. Refresh again; previous collection kept."
        )
    if revision is not None:
        probe = s.slsk("shares/library?" + urlencode({"limit": 1, "revision": revision}))
        if probe.get("revision") != revision or not probe.get("complete"):
            raise ValueError("slskd changed during import. Previous collection kept.")
    return list(tracks.values()), len(mappings)


def import_cache(s, refresh=False):
    try:
        wait_ready(s, refresh)
        direct = metadata_inventory(s)
        if direct is not None:
            tracks, roots = direct
            with s.db() as c:
                c.execute("DELETE FROM tracks")
                c.executemany("INSERT INTO tracks VALUES (?,?,?,?,?,?,?,?)", tracks)
            s.scan_state.update(
                phase="done",
                lastSync=time.time(),
                source="slskd",
                metadataSource="slskd-cache",
                count=len(tracks),
                total=len(tracks),
                roots=roots,
                tagsRead=0,
            )
            return
        s.scan_state.update(phase="inventory", metadataSource="local-fallback")
        files, roots = local_inventory(s)
        try:
            from mutagen import File
        except ImportError:
            File = None
        with s.db() as c:
            cached = {r["path"]: dict(r) for r in c.execute("SELECT * FROM track_metadata")}
            old = {
                os.path.normcase(os.path.realpath(r["path"])): dict(r)
                for r in c.execute("SELECT * FROM tracks")
            }
        tracks = []
        metadata = []
        unreadable = 0
        reread = 0
        s.scan_state.update(phase="metadata", total=len(files), roots=roots)
        for canonical, (path, root, f) in files.items():
            previous = cached.get(canonical)
            fingerprint = None
            try:
                stat = path.stat()
                fingerprint = (str(stat.st_size), str(stat.st_mtime_ns))
            except OSError:
                unreadable += 1
            if previous and fingerprint == (previous["size"], previous["mtime"]):
                row = json.loads(previous["value"])
            elif fingerprint is None and canonical in old:
                row = old[canonical]
            else:
                row = {
                    "path": canonical,
                    "root": str(root),
                    "artist": "",
                    "album": path.parent.name,
                    "title": s.filename_title(str(path)),
                    "duration": s.attr(f, "length", 1),
                    "format": path.suffix[1:].lower(),
                    "size": f.get("size", 0),
                }
                if File and fingerprint is not None:
                    reread += 1
                    try:
                        audio = File(path, easy=True)
                        if audio is None:
                            raise ValueError("Metadata could not be read")
                        if audio is not None:
                            row.update(
                                artist=(audio.get("artist") or [""])[0],
                                album=(audio.get("album") or [row["album"]])[0],
                                title=(audio.get("title") or [row["title"]])[0],
                                duration=getattr(audio.info, "length", row["duration"]),
                            )
                    except Exception:
                        unreadable += 1
                        if canonical in old:
                            row.update(
                                {
                                    k: old[canonical][k]
                                    for k in ("artist", "album", "title", "duration")
                                }
                            )
                        fingerprint = None
                elif not File and canonical in old:
                    row.update({k: old[canonical][k] for k in ("artist", "album", "title")})
                if fingerprint is not None and File:
                    metadata.append((canonical, *fingerprint, json.dumps(row)))
            row.update(path=canonical, root=str(root), size=f.get("size", row["size"]))
            tracks.append(
                tuple(
                    row[k]
                    for k in (
                        "path",
                        "root",
                        "artist",
                        "album",
                        "title",
                        "duration",
                        "format",
                        "size",
                    )
                )
            )
            s.scan_state.update(count=len(tracks), tagsRead=reread)
        # Publish a full snapshot only after the upstream scan and inventory succeeded.
        with s.db() as c:
            c.execute("DELETE FROM tracks")
            c.executemany("INSERT INTO tracks VALUES (?,?,?,?,?,?,?,?)", tracks)
            c.executemany("INSERT OR REPLACE INTO track_metadata VALUES (?,?,?,?)", metadata)
            c.execute("DELETE FROM track_metadata WHERE path NOT IN (SELECT path FROM tracks)")
        s.scan_state.update(
            phase="done",
            lastSync=time.time(),
            warning=(
                f"{unreadable} files could not be read fully; cached tags or filename details are shown."
                if unreadable
                else ""
            ),
            source="slskd",
        )
    except Exception as e:
        s.scan_state.update(error=str(e))
        s.diag.error(e, operation="share-library-sync")
    finally:
        s.scan_state["running"] = False
        s.scan_lock.release()


def start(s, refresh=False):
    if not s.scan_lock.acquire(False):
        raise ValueError("A collection refresh is already running.")
    s.scan_state.update(
        running=True,
        count=0,
        error=None,
        warning="",
        phase="slskd",
        source="slskd",
        total=0,
        tagsRead=0,
    )
    threading.Thread(target=import_cache, args=(s, refresh), daemon=True).start()
    return dict(s.scan_state)
