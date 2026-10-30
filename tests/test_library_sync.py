import json, tempfile, unittest, wave, os
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server, library_sync, features


class LinkedLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = server.DATA
        server.DATA = Path(self.tmp.name) / "data"
        server.init()
        self.music = Path(self.tmp.name) / "music"
        self.music.mkdir()
        self.album = self.music / "Artist" / "Album"
        self.album.mkdir(parents=True)
        self.audio = self.album / "01 - Song.wav"
        with wave.open(str(self.audio), "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\0\0" * 8000)
        self.contents = [
            {
                "name": r"Music\Artist\Album",
                "files": [
                    {
                        "filename": self.audio.name,
                        "size": self.audio.stat().st_size,
                        "length": 1,
                    },
                    {"filename": "cover.jpg", "size": 8},
                ],
            }
        ]
        server.scan_state.clear()
        server.scan_state.update(running=False, count=0, error=None)

    def tearDown(self):
        server.DATA = self.old
        self.tmp.cleanup()

    def upstream(self, path, method="GET", body=None):
        if path == "application":
            return {"shares": {"ready": True, "scanning": False, "scanPending": False}}
        if path == "shares":
            return {"local": [{"localPath": str(self.music), "remotePath": "Music"}]}
        if path.startswith("shares/library?"):
            raise server.UpstreamError("Unsupported endpoint", status=404)
        if path == "shares/contents":
            return self.contents
        raise AssertionError((path, method))

    def run_import(self):
        server.scan_lock.acquire()
        library_sync.import_cache(server)
        self.assertIsNone(server.scan_state.get("error"))

    def test_import_uses_share_inventory_and_reuses_unchanged_tags(self):
        import mutagen

        original = mutagen.File
        with (
            patch.object(server, "slsk", side_effect=self.upstream) as remote,
            patch("mutagen.File", wraps=original) as read,
        ):
            self.run_import()
            self.assertEqual(read.call_count, 1)
            self.run_import()
            self.assertEqual(read.call_count, 1)
            self.assertFalse(
                any(len(c.args) > 1 and c.args[1] == "PUT" for c in remote.call_args_list)
            )
            # A changed timestamp invalidates the tag entry even when the size is unchanged.
            stat = self.audio.stat()
            os.utime(self.audio, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000))
            self.run_import()
            self.assertEqual(read.call_count, 2)
        with server.db() as c:
            rows = c.execute("SELECT * FROM tracks").fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["title"], "Song")
            self.assertEqual(rows[0]["album"], "Album")
        self.assertTrue(self.audio.exists())

    def test_alias_resolves_and_inventory_removal_prunes_only_index(self):
        alias = Path(self.tmp.name) / "link"
        alias.symlink_to(self.music, target_is_directory=True)
        with patch.object(server, "slsk", side_effect=self.upstream):
            self.run_import()

        def linked(path, method="GET", body=None):
            if path == "shares":
                return {"local": [{"localPath": str(alias), "remotePath": "Music"}]}
            return self.upstream(path, method, body)

        with patch.object(server, "slsk", side_effect=linked):
            self.run_import()
        with server.db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM tracks").fetchone()[0], 1)
        self.contents = []
        with patch.object(server, "slsk", side_effect=linked):
            self.run_import()
        with server.db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM tracks").fetchone()[0], 0)
        self.assertTrue(self.audio.exists())

    def test_failed_upstream_keeps_previous_collection(self):
        with patch.object(server, "slsk", side_effect=self.upstream):
            self.run_import()
        with patch.object(server, "slsk", side_effect=ValueError("offline")):
            server.scan_lock.acquire()
            library_sync.import_cache(server)
        self.assertIn("offline", server.scan_state["error"])
        with server.db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM tracks").fetchone()[0], 1)

    def test_refresh_requests_slskd_scan_and_waits_before_reading_inventory(self):
        states = [
            {"ready": True, "scanning": False},
            {"scanning": True, "scanProgress": 0.5},
            {"ready": True, "scanning": False},
        ]
        calls = []

        def upstream(path, method="GET", body=None):
            calls.append((path, method))
            if path == "application":
                return {"shares": states.pop(0)}
            if path == "shares" and method == "PUT":
                return {}
            return self.upstream(path, method, body)

        with (
            patch.object(server, "slsk", side_effect=upstream),
            patch.object(library_sync.time, "sleep"),
        ):
            server.scan_lock.acquire()
            library_sync.import_cache(server, True)
        self.assertIsNone(server.scan_state.get("error"))
        self.assertLess(calls.index(("shares", "PUT")), calls.index(("shares/contents", "GET")))
        self.assertEqual(states, [])

    def test_clear_only_successful_downloads_preserves_history_and_failed_requests(
        self,
    ):
        rows = [
            {"id": "ok", "filename": "ok.wav", "state": "Completed, Succeeded"},
            {"id": "failed", "filename": "bad.wav", "state": "Completed, Errored"},
            {"id": "queued", "filename": "next.wav", "state": "Queued"},
        ]
        for f in rows:
            server.save_request(
                {
                    "id": f["id"],
                    "file": {"username": "person", "filename": f["filename"]},
                    "status": f["state"],
                }
            )
        with patch.object(
            server,
            "slsk",
            side_effect=lambda path, *args: (
                [{"username": "person", "directories": [{"files": rows}]}]
                if path == "transfers/downloads"
                else {}
            ),
        ) as remote:
            result = features.clear_completed(server, "downloads")
        self.assertEqual(result["cleared"], 1)
        self.assertEqual(
            remote.call_args_list[-1].args,
            ("transfers/downloads/person/ok?remove=true", "DELETE"),
        )
        self.assertEqual(remote.call_count, 2)
        with server.db() as c:
            rs = {r["id"]: json.loads(r["value"]) for r in c.execute("SELECT * FROM requests")}
        self.assertTrue(rs["ok"]["archived"])
        self.assertFalse(rs["failed"].get("archived", False))
        self.assertEqual(len(rs), 3)

    def test_failed_removal_is_not_archived(self):
        server.save_request(
            {
                "id": "ok",
                "file": {"username": "person", "filename": "ok.wav"},
                "status": "Completed, Succeeded",
            }
        )

        def upstream(path, *args):
            if path == "transfers/downloads":
                return [
                    {
                        "username": "person",
                        "directories": [
                            {
                                "files": [
                                    {
                                        "id": "ok",
                                        "filename": "ok.wav",
                                        "state": "Completed, Succeeded",
                                    }
                                ]
                            }
                        ],
                    }
                ]
            raise ValueError("failed")

        with patch.object(server, "slsk", side_effect=upstream):
            r = features.clear_completed(server, "downloads")
        self.assertEqual(r["cleared"], 0)
        self.assertTrue(r["warnings"])
        with server.db() as c:
            self.assertFalse(
                json.loads(c.execute("SELECT value FROM requests").fetchone()[0]).get(
                    "archived", False
                )
            )


if __name__ == "__main__":
    unittest.main()
