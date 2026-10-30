"""Recoverable two-store changes for the private engine YAML and local settings."""

from pathlib import Path
import hashlib, json, os, time, uuid


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def commit(s, path, content, changes):
    raw = path.read_bytes()
    new = content.encode("utf-8")
    ident = str(uuid.uuid4())
    before = {k: s.settings(True).get(k) for k in changes}
    backup = s.DATA / "config-backups" / (ident + ".yml")
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_bytes(raw)
    try:
        os.chmod(backup, 0o600)
    except OSError:
        pass
    operation = {
        "path": str(path),
        "backup": str(backup),
        "beforeHash": digest(raw),
        "afterHash": digest(new),
        "before": before,
        "changes": changes,
        "phase": "prepared",
        "created": time.time(),
    }
    with s.db() as c:
        c.execute("INSERT INTO config_operations VALUES (?,?)", (ident, json.dumps(operation)))
    temp = path.with_name(path.name + ".resonance.tmp")
    temp.write_bytes(new)
    try:
        os.replace(temp, path)
        from storage import settings_patch

        settings_patch(s, changes)
        operation["phase"] = "committed"
    except Exception:
        restore = path.with_name(path.name + ".resonance.restore")
        restore.write_bytes(raw)
        os.replace(restore, path)
        # A patch can commit before a later I/O exception. Restore both stores.
        # Leave the journal prepared if restoration fails so startup retries it.
        from storage import settings_patch

        settings_patch(s, before)
        operation["phase"] = "rolled-back"
        raise
    finally:
        with s.db() as c:
            c.execute(
                "UPDATE config_operations SET value=? WHERE id=?",
                (json.dumps(operation), ident),
            )


def recover(s):
    with s.db() as c:
        operations = c.execute("SELECT id,value FROM config_operations").fetchall()
    for row in operations:
        op = json.loads(row["value"])
        if op["phase"] != "prepared":
            continue
        path = Path(op["path"])
        try:
            actual = digest(path.read_bytes())
            from storage import settings_patch

            if actual == op["afterHash"]:
                settings_patch(s, op["changes"])
                op["phase"] = "committed"
            elif actual == op["beforeHash"]:
                settings_patch(s, op["before"])
                op["phase"] = "rolled-back"
            else:
                op["phase"] = "needs-review"
                s.diag.event(
                    "config-recovery-warning",
                    "WARNING",
                    message="The configuration changed externally. Check sharing settings before resuming.",
                )
            with s.db() as c:
                c.execute(
                    "UPDATE config_operations SET value=? WHERE id=?",
                    (json.dumps(op), row["id"]),
                )
        except OSError:
            s.diag.event(
                "config-recovery-warning",
                "WARNING",
                message="A pending configuration file is unavailable. Restore its private backup before changing sharing.",
            )
