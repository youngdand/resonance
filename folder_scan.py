"""Stage a complete selected-root snapshot; incomplete enumeration never publishes."""

from pathlib import Path
import os


def run(s, roots):
    try:
        bases = [Path(r).expanduser().resolve() for r in roots]
        if not bases or any(not p.is_dir() for p in bases):
            raise ValueError(
                "Every configured collection folder must be available before scanning."
            )
        s.scan_state.update(
            running=True,
            count=0,
            error=None,
            warning="",
            source="folders",
            phase="folders",
            total=0,
            tagsRead=0,
            roots=len(bases),
        )
        try:
            from mutagen import File
        except ImportError:
            File = None
        with s.db() as c:
            old = {
                os.path.normcase(os.path.realpath(r["path"])): dict(r)
                for r in c.execute("SELECT * FROM tracks")
            }
        staged = {}
        warnings = 0

        def fail(error):
            raise error

        for base in bases:
            for directory, _, files in os.walk(base, onerror=fail):
                for name in files:
                    p = Path(directory) / name
                    if p.suffix.lower() not in s.AUDIO:
                        continue
                    canonical = os.path.normcase(os.path.realpath(p))
                    previous = old.get(canonical)
                    try:
                        size = p.stat().st_size
                    except OSError:
                        warnings += 1
                        if previous:
                            staged[canonical] = tuple(
                                previous[k]
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
                        continue
                    row = {
                        "path": canonical,
                        "root": str(base),
                        "artist": "",
                        "album": p.parent.name,
                        "title": s.filename_title(str(p)),
                        "duration": 0,
                        "format": p.suffix[1:].lower(),
                        "size": size,
                    }
                    try:
                        if File:
                            audio = File(p, easy=True)
                            if audio is None:
                                raise ValueError("Unrecognized audio metadata")
                            row.update(
                                artist=(audio.get("artist") or [""])[0],
                                album=(audio.get("album") or [row["album"]])[0],
                                title=(audio.get("title") or [row["title"]])[0],
                                duration=getattr(audio.info, "length", 0),
                            )
                        elif previous:
                            row.update(
                                {k: previous[k] for k in ("artist", "album", "title", "duration")}
                            )
                    except Exception:
                        warnings += 1
                        if previous:
                            row.update(
                                {k: previous[k] for k in ("artist", "album", "title", "duration")}
                            )
                    staged[canonical] = tuple(
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
                    s.scan_state["count"] = len(staged)
        if any(not p.is_dir() for p in bases):
            raise ValueError("A collection drive became unavailable. Previous snapshot retained.")
        with s.db() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("DELETE FROM tracks")
            c.executemany("INSERT INTO tracks VALUES (?,?,?,?,?,?,?,?)", staged.values())
        s.scan_state.update(
            phase="done",
            warning=(
                f"{warnings} files retained cached tags or filename details." if warnings else ""
            ),
        )
    except Exception as exc:
        s.scan_state["error"] = str(exc)
        s.diag.error(exc, operation="folder-scan")
    finally:
        s.scan_state["running"] = False
        s.scan_lock.release()
