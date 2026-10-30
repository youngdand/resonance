import json, tempfile, unittest, threading, wave
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from urllib.request import Request, urlopen
from urllib.error import HTTPError


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = server.DATA
        server.DATA = Path(self.tmp.name) / "data"
        server.init()

    def tearDown(self):
        server.DATA = self.old
        self.tmp.cleanup()

    def test_matching_is_conservative(self):
        t = {"title": "Angel", "artist": "Massive Attack", "duration": 300}
        f = {
            "filename": r"Music\Massive Attack\Mezzanine\01 - Angel.flac",
            "duration": 301,
        }
        self.assertEqual(server.owned(f, [t]), "owned")
        self.assertEqual(server.owned({**f, "duration": 320}, [t]), "possible")
        self.assertEqual(
            server.owned({"filename": r"Other Artist\Angel.flac", "duration": 301}, [t]),
            "possible",
        )
        self.assertEqual(server.owned({"filename": "Unrelated.flac"}, [t]), "new")

    def test_scan_reads_audio_and_removes_only_missing_files(self):
        folder = Path(self.tmp.name) / "music"
        folder.mkdir()
        audio = folder / "01 - Example.wav"
        with wave.open(str(audio), "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\0\0" * 8000)
        server.scan_lock.acquire()
        server.scan([str(folder)])
        with server.db() as c:
            row = c.execute("SELECT * FROM tracks").fetchone()
        self.assertEqual(row["title"], "Example")
        self.assertTrue(audio.exists())
        audio.unlink()
        server.scan_lock.acquire()
        server.scan([str(folder)])
        with server.db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM tracks").fetchone()[0], 0)

    def test_result_attributes(self):
        f = server.flatten(
            [
                {
                    "username": "a",
                    "hasFreeUploadSlot": True,
                    "files": [
                        {
                            "filename": "track.flac",
                            "size": 123,
                            "attributes": [
                                {"type": 1, "value": 240},
                                {"type": 4, "value": 44100},
                            ],
                        }
                    ],
                }
            ]
        )[0]
        self.assertEqual(f["duration"], 240)
        self.assertEqual(f["sampleRate"], 44100)

    def test_failed_enqueue_does_not_replace_original(self):
        old = {
            "id": "old",
            "query": "artist track",
            "file": {"username": "a", "filename": "x.flac", "size": 1},
            "status": "Rejected",
            "attempts": [],
        }
        server.save_request(old)
        with patch.object(server, "slsk", return_value={"enqueued": [], "failed": [{}]}):
            self.assertEqual(
                server.queue_file(
                    {"username": "b", "filename": "x.flac", "size": 1},
                    "artist track",
                    "old",
                )["status"],
                "Unconfirmed",
            )
        with server.db() as c:
            self.assertEqual(
                json.loads(c.execute("SELECT value FROM requests").fetchone()[0])["status"],
                "Rejected",
            )

    def test_replacement_keeps_original_search_and_attempts(self):
        old = {
            "id": "old",
            "query": "artist track",
            "file": {"username": "a", "filename": "x.flac", "size": 1},
            "status": "Rejected",
            "attempts": [],
        }
        server.save_request(old)
        with patch.object(
            server,
            "slsk",
            return_value={"enqueued": [{"id": "transfer"}], "failed": []},
        ):
            r = server.queue_file(
                {"username": "b", "filename": "x.flac", "size": 1}, old["query"], "old"
            )
        self.assertEqual(r["query"], "artist track")
        self.assertEqual(r["attempts"], [old["file"]])
        with server.db() as c:
            self.assertEqual(
                json.loads(
                    c.execute("SELECT value FROM requests WHERE id=?", ("old",)).fetchone()[0]
                )["status"],
                "Replaced",
            )

    def test_no_duplicate_or_active_replacement(self):
        f = {"username": "a", "filename": "x.flac", "size": 1}
        server.save_request({"id": "old", "file": f, "status": "Queued"})
        self.assertEqual(server.queue_file(f, "q")["id"], "old")
        with self.assertRaises(ValueError):
            server.queue_file({**f, "username": "b"}, "q", "old")

    def test_secret_not_returned_and_post_guard(self):
        with server.db() as c:
            c.execute(
                "INSERT INTO settings VALUES (1,?)",
                (json.dumps({"key": "secret-test"}),),
            )
        h = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        t = threading.Thread(target=h.serve_forever, daemon=True)
        t.start()
        try:
            base = f"http://127.0.0.1:{h.server_port}"
            with urlopen(base + "/api/state") as r:
                d = json.load(r)
            self.assertNotIn("key", d["settings"])
            self.assertTrue(d["settings"]["hasKey"])
            with self.assertRaises(HTTPError) as err:
                urlopen(
                    Request(
                        base + "/api/settings",
                        data=b"{}",
                        headers={"Content-Type": "application/json"},
                    )
                )
            self.assertEqual(err.exception.code, 403)
            with urlopen(
                Request(
                    base + "/api/settings",
                    data=b'{"formats":["flac"]}',
                    headers={
                        "Content-Type": "application/json",
                        "X-Resonance-Token": d["token"],
                    },
                )
            ) as r:
                self.assertEqual(r.status, 200)
        finally:
            h.shutdown()
            h.server_close()
            t.join()


if __name__ == "__main__":
    unittest.main()
