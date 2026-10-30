"""Explicit SQLite lifetimes, atomic settings patches and revisioned migrations."""

import json, sqlite3


class Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect(path):
    c = sqlite3.connect(path, timeout=30, factory=Connection)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


def settings_patch(s, values):
    if not isinstance(values, dict):
        raise ValueError("Settings must be an object.")
    with s.db() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT value FROM settings WHERE id=1").fetchone()
        current = json.loads(row[0]) if row else {}
        if not isinstance(current, dict):
            raise ValueError("Saved settings are invalid. Restore a private data backup.")
        current.update(values)
        c.execute("INSERT OR REPLACE INTO settings VALUES (1,?)", (json.dumps(current),))


def migrate(s):
    with s.db() as c:
        c.executescript(
            """
    CREATE TABLE IF NOT EXISTS schema_version (id INTEGER PRIMARY KEY CHECK(id=1),version INTEGER NOT NULL);
    INSERT OR IGNORE INTO schema_version VALUES (1,1);
    CREATE TABLE IF NOT EXISTS library_revision (id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL);
    INSERT OR IGNORE INTO library_revision VALUES (1,0);
    CREATE TRIGGER IF NOT EXISTS library_insert AFTER INSERT ON tracks BEGIN UPDATE library_revision SET revision=revision+1 WHERE id=1; END;
    CREATE TRIGGER IF NOT EXISTS library_update AFTER UPDATE ON tracks BEGIN UPDATE library_revision SET revision=revision+1 WHERE id=1; END;
    CREATE TRIGGER IF NOT EXISTS library_delete AFTER DELETE ON tracks BEGIN UPDATE library_revision SET revision=revision+1 WHERE id=1; END;
    CREATE TABLE IF NOT EXISTS queue_keys (username TEXT,filename TEXT,request_id TEXT NOT NULL,PRIMARY KEY(username,filename));
    CREATE TABLE IF NOT EXISTS release_aliases (old_id TEXT PRIMARY KEY,new_id TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS config_operations (id TEXT PRIMARY KEY,value TEXT NOT NULL);
    """
        )


_schema_lock = __import__("threading").RLock()
_schemas = set()


def ensure_schema(s, name, sql):
    key = (str(s.DATA.resolve()), name)
    with _schema_lock:
        if key in _schemas:
            return
        with s.db() as c:
            c.executescript(sql)
        _schemas.add(key)


def backup_before_migration(data):
    """Keep a restorable private snapshot before upgrading an existing unversioned store."""
    from pathlib import Path
    import time, uuid, os

    path = Path(data) / "resonance.db"
    if not path.exists():
        return
    with connect(path) as source:
        if source.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'"
        ).fetchone():
            return
        directory = Path(data) / "backups"
        directory.mkdir(exist_ok=True)
        target = directory / ("before-rc1-" + str(uuid.uuid4()) + ".sqlite3")
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close()
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
