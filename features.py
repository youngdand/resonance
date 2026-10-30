"""Album folder resolution, outgoing shares and private messaging."""

from pathlib import Path
from urllib.parse import quote
import json, re, time, os, threading, shutil

config_lock = threading.Lock()
browse_cache = {}
ARTWORK = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
    ".avif",
    ".pdf",
}


def user(value):
    value = str(value or "").strip()
    if not value or len(value) > 200:
        raise ValueError("Enter a valid Soulseek username.")
    return value


def transfer_rows(data):
    return [
        {**f, "username": u["username"]}
        for u in data
        for d in u.get("directories", [])
        for f in d.get("files", [])
    ]


def succeeded(state):
    from transfer_state import succeeded as success

    return success(state)


def clear_completed(s, direction):
    if direction not in ("downloads", "uploads"):
        raise ValueError("Invalid transfer list.")
    # The bulk endpoint also clears failures. Remove only successful snapshot rows instead.
    rows = transfer_rows(s.slsk("transfers/" + direction))
    removed = set()
    warnings = []
    for f in rows:
        if not succeeded(f.get("state")):
            continue
        try:
            s.slsk(
                "transfers/"
                + direction
                + "/"
                + quote(f["username"], safe="")
                + "/"
                + quote(str(f["id"]), safe="")
                + "?remove=true",
                "DELETE",
            )
            removed.add((f["username"], f["filename"]))
        except ValueError:
            warnings.append("Some completed transfers could not be cleared. Refresh and try again.")
    archived = 0
    if direction == "downloads":
        present = {(f["username"], f["filename"]) for f in rows}
        with s.db() as c:
            for row in c.execute("SELECT id,value FROM requests").fetchall():
                r = json.loads(row["value"])
                key = (r["file"]["username"], r["file"]["filename"])
                if key in removed:
                    r["status"] = "Completed, Succeeded"
                if (
                    succeeded(r.get("status"))
                    and (key in removed or key not in present)
                    and not r.get("archived")
                ):
                    r["archived"] = True
                    archived += 1
                    c.execute(
                        "UPDATE requests SET value=? WHERE id=?",
                        (json.dumps(r), row["id"]),
                    )
    return {
        "cleared": max(len(removed), archived),
        "warnings": list(dict.fromkeys(warnings)),
    }


def browse_rows(s, username):
    cached = browse_cache.get(username)
    if cached and time.time() - cached[0] < 120:
        return cached[1]
    result = s.slsk("users/" + quote(username, safe="") + "/browse")
    dirs = result if isinstance(result, list) else result.get("directories", [])
    rows = []
    for d in dirs:
        directory = d.get("name", d.get("directory", ""))
        for raw in d.get("files", []):
            f = dict(raw)
            name = f.get("filename", "")
            if directory and not name.replace("\\", "/").startswith(
                directory.replace("\\", "/") + "/"
            ):
                f["filename"] = directory.rstrip("\\/") + "\\" + name
            rows.extend(s.flatten([{"username": username, "files": [f]}]))
    browse_cache[username] = (time.time(), rows)
    return rows


def directory_rows(s, username, directory):
    result = s.slsk(
        "users/" + quote(username, safe="") + "/directory",
        "POST",
        {"directory": directory.replace("/", "\\")},
    )
    dirs = result if isinstance(result, list) else result.get("directories", [])
    rows = []
    for d in dirs:
        name = d.get("name", d.get("directory", "")).replace("\\", "/").rstrip("/")
        if name != directory and not name.startswith(directory + "/"):
            continue
        for raw in d.get("files", []):
            f = dict(raw)
            filename = f.get("filename", "").replace("\\", "/")
            if not filename.startswith(name + "/"):
                filename = name + "/" + filename
            f["filename"] = filename.replace("/", "\\")
            rows.extend(s.flatten([{"username": username, "files": [f]}]))
    return rows


def album_folder(s, username, directory):
    username = user(username)
    directory = str(directory).replace("\\", "/").rstrip("/")
    if not directory:
        raise ValueError("No album folder supplied.")
    direct = None
    try:
        direct = directory_rows(s, username, directory)
    except ValueError as e:
        # Legacy versions/peers can lack the directory operation. Expected peer failures remain useful errors.
        if getattr(e, "code", None) in ("user_offline", "soulseek_disconnected"):
            raise
    # Keep full inventory discovery for nested discs and artwork: a single directory response
    # does not prove that no additional subfolders exist.
    rows = browse_rows(s, username)
    if direct:
        direct_dirs = {f["filename"].replace("\\", "/").rsplit("/", 1)[0] for f in direct}
        rows = [
            f for f in rows if f["filename"].replace("\\", "/").rsplit("/", 1)[0] not in direct_dirs
        ] + direct
    contents = [
        dict(f) for f in rows if f["filename"].replace("\\", "/").startswith(directory + "/")
    ]
    selected = [f for f in contents if Path(f["filename"]).suffix.lower() in s.AUDIO]
    artwork = [f for f in contents if Path(f["filename"]).suffix.lower() in ARTWORK]
    if not selected:
        raise ValueError(
            "No accessible audio files found in this folder. The user may have gone offline or restricted access."
        )
    return {
        "files": s.annotate(selected),
        "artwork": artwork,
        "totalFiles": len(contents),
        "username": username,
        "directory": directory,
        "verifiedFolder": True,
    }


def config_path(s):
    value = s.settings(True).get("slskdConfig", "")
    if not value:
        raise ValueError("Add your actual slskd.yml path in Settings to enable sharing controls.")
    p = Path(value).expanduser()
    if not p.is_absolute() or p.suffix.lower() not in (".yml", ".yaml") or not p.is_file():
        raise ValueError(
            "The slskd configuration file was not found. Check its full path in Settings."
        )
    return p


def yaml_module():
    try:
        import ruamel.yaml, io

        class RoundTrip:
            @staticmethod
            def safe_load(text):
                return ruamel.yaml.YAML(typ="rt").load(text)

            @staticmethod
            def safe_dump(value, **kwargs):
                stream = io.StringIO()
                yaml = ruamel.yaml.YAML(typ="rt")
                yaml.preserve_quotes = True
                yaml.dump(value, stream)
                return stream.getvalue()

        return RoundTrip
    except ImportError:
        raise ValueError("Install requirements.txt before using sharing controls.") from None


def share_path(value):
    raw = value
    if value.startswith(("-", "!")):
        value = value[1:]
    if value.startswith("["):
        match = re.match(r"^\[([^\]\\/]+)\](.+)$", value)
        if not match:
            raise ValueError("A share alias must have a name and an absolute folder.")
        value = match[2]
    if not Path(value).is_absolute() or not Path(value).is_dir():
        raise ValueError(
            "Each share must reference an existing absolute folder, optionally prefixed by [alias] or ! exclusion."
        )
    return raw


def config_read(s):
    y = yaml_module()
    data = y.safe_load(config_path(s).read_text(encoding="utf-8-sig")) or {}
    if not isinstance(data, dict):
        raise ValueError("Invalid slskd configuration.")
    return data


def control_state(s):
    c = config_read(s)
    saved = s.settings(True)
    return {
        "directories": (c.get("shares") or {}).get("directories") or [],
        "blockedUsers": (
            ((c.get("transfers") or {}).get("groups") or {}).get("blacklisted") or {}
        ).get("members")
        or [],
        "paused": saved.get("sharingPaused", False),
        "resumeDirectories": saved.get("resumeDirectories", []),
        "configPath": str(config_path(s)),
    }


def store_settings(s, values):
    import storage

    storage.settings_patch(s, values)


def control_update(s, b):
    action = b.get("action")
    if action not in ("block", "unblock", "folders", "pause", "resume"):
        raise ValueError("Unknown sharing action.")
    with config_lock:
        c = config_read(s)
        p = config_path(s)
        y = yaml_module()
        saved = s.settings(True)
        if (c.get("flags") or {}).get("no_config_watch"):
            raise ValueError(
                "slskd configuration watching is disabled. Enable it before using live sharing controls."
            )
        shares = c.setdefault("shares", {})
        dirs = shares.get("directories") or []
        changes = {}
        target = None
        if action in ("block", "unblock"):
            target = user(b.get("username"))
            groups = c.setdefault("transfers", {}).setdefault("groups", {})
            blocked = groups.setdefault("blacklisted", {})
            members = blocked.get("members") or []
            members = [m for m in members if m.casefold() != target.casefold()]
            if action == "block":
                members.append(target)
            blocked["members"] = members
        elif action == "folders":
            folders = b.get("directories")
            if not isinstance(folders, list) or not all(isinstance(x, str) for x in folders):
                raise ValueError("Folders must be a list of share entries.")
            folders = [share_path(x) for x in folders]
            if saved.get("sharingPaused"):
                changes["resumeDirectories"] = folders
            else:
                shares["directories"] = folders
        elif action == "pause":
            if not saved.get("sharingPaused"):
                changes.update(resumeDirectories=dirs, sharingPaused=True)
            shares["directories"] = []
        elif action == "resume":
            shares["directories"] = saved.get("resumeDirectories", dirs)
            changes["sharingPaused"] = False
        content = y.safe_dump(c, sort_keys=False, allow_unicode=True)
        if y.safe_load(content) != c:
            raise ValueError("Configuration validation failed.")
        import config_journal

        config_journal.commit(s, p, content, changes)
    warnings = []
    cancelled = 0
    if action in ("block", "pause", "folders"):
        try:
            for f in transfer_rows(s.slsk("transfers/uploads")):
                if not re.search(
                    r"succeeded|completed|cancelled|errored|rejected",
                    f.get("state", ""),
                    re.I,
                ) and (action != "block" or f["username"].casefold() == target.casefold()):
                    try:
                        s.slsk(
                            "transfers/uploads/"
                            + quote(f["username"], safe="")
                            + "/"
                            + quote(str(f["id"]), safe=""),
                            "DELETE",
                        )
                        cancelled += 1
                    except ValueError:
                        warnings.append(
                            "Some transfers could not be cancelled. Refresh Uploads and stop any remaining transfers."
                        )
        except ValueError:
            warnings.append("Could not read current uploads to cancel them. Refresh Uploads.")
    if action in ("folders", "pause", "resume"):
        # Configuration watching is asynchronous. Wait for the specific folder change before rescanning.
        expected = c.get("shares", {}).get("directories") or []
        applied = False
        for _ in range(12):
            try:
                current = s.slsk("shares")
                actual = [
                    x.get("raw", x.get("localPath", "")).rstrip("\\/")
                    for x in current.get("local", [])
                ]
                if "local" in current and set(actual) == {x.rstrip("\\/") for x in expected}:
                    applied = True
                    break
            except ValueError:
                break
            time.sleep(0.25)
        if applied:
            try:
                s.slsk("shares", "PUT")
            except ValueError:
                warnings.append(
                    "Share rescan could not start; refresh or restart slskd to finish applying the folders."
                )
        else:
            warnings.append(
                "Configuration saved. slskd has not confirmed the new folders yet; restart slskd if they do not update."
            )
    else:
        warnings.append(
            "Blocklist saved. slskd applies it through configuration watching; restart slskd if the change does not take effect."
        )
    return {
        **control_state(s),
        "cancelled": cancelled,
        "warnings": warnings,
        "message": "Configuration saved; share scans may take time. YAML comments are preserved. Private recovery backups remain on this computer.",
    }


def get_route(h, path, q, s):
    if path == "/api/album-folder":
        h.send_json(album_folder(s, q.get("username", [""])[0], q.get("directory", [""])[0]))
        return True
    if path == "/api/uploads":
        h.send_json(transfer_rows(s.slsk("transfers/uploads")))
        return True
    if path == "/api/sharing":
        h.send_json(control_state(s))
        return True
    if path == "/api/conversations":
        h.send_json(s.slsk("conversations"))
        return True
    if path == "/api/messages":
        username = user(q.get("username", [""])[0])
        convs = s.slsk("conversations?includeInactive=true")
        exists = any(c.get("username", "").casefold() == username.casefold() for c in convs)
        h.send_json(
            s.slsk("conversations/" + quote(username, safe="") + "/messages") if exists else []
        )
        return True
    return False


def post_route(h, path, b, s):
    if path == "/api/clear-completed":
        h.send_json(clear_completed(s, b.get("direction")))
        return True
    if path == "/api/sharing":
        h.send_json(control_update(s, b))
        return True
    if path == "/api/stop-upload":
        username = user(b.get("username"))
        tid = str(b.get("id", ""))
        if not tid:
            raise ValueError("Missing transfer ID.")
        s.slsk(
            "transfers/uploads/" + quote(username, safe="") + "/" + quote(tid, safe=""),
            "DELETE",
        )
        h.send_json({"ok": True})
        return True
    if path == "/api/send-message":
        username = user(b.get("username"))
        message = str(b.get("message", "")).strip()
        if not message or len(message) > 5000:
            raise ValueError("Enter a message of 1–5,000 characters.")
        s.slsk("conversations/" + quote(username, safe=""), "POST", message)
        h.send_json({"ok": True})
        return True
    if path == "/api/read-messages":
        s.slsk("conversations/" + quote(user(b.get("username")), safe=""), "PUT")
        h.send_json({"ok": True})
        return True
    return False
