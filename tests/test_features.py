import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server, features, yaml


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = server.DATA
        server.DATA = Path(self.tmp.name) / "data"
        server.init()
        self.path = Path(self.tmp.name) / "slskd.yml"
        self.config = {
            "soulseek": {"username": "test", "password": "keep-me"},
            "web": {"authentication": {"api_keys": {"test": {"key": "keep-key"}}}},
            "shares": {"directories": [self.tmp.name]},
            "transfers": {"groups": {"blacklisted": {"members": ["existing"]}}},
        }
        self.path.write_text(yaml.safe_dump(self.config))
        features.store_settings(server, {"slskdConfig": str(self.path)})
        features.browse_cache.clear()

    def tearDown(self):
        server.DATA = self.old
        server.diag.close()
        self.tmp.cleanup()

    def upstream(self, path, method="GET", body=None):
        if path == "shares":
            return {
                "local": [
                    {"raw": x}
                    for x in yaml.safe_load(self.path.read_text())
                    .get("shares", {})
                    .get("directories", [])
                ]
            }
        if path == "transfers/uploads":
            return [
                {
                    "username": "blocked",
                    "directories": [
                        {
                            "files": [
                                {
                                    "id": "a",
                                    "filename": "x.flac",
                                    "state": "InProgress, Transferring",
                                }
                            ]
                        }
                    ],
                },
                {
                    "username": "other",
                    "directories": [
                        {"files": [{"id": "b", "filename": "y.flac", "state": "Queued"}]}
                    ],
                },
            ]
        return {}

    def test_album_fetch_includes_discs_but_not_adjacent_albums(self):
        dirs = [
            {
                "name": r"Music\Artist\Album",
                "files": [
                    {"filename": "01.flac", "size": 1},
                    {"filename": "cover.jpg", "size": 1},
                ],
            },
            {
                "name": r"Music\Artist\Album\Disc 2",
                "files": [{"filename": "02.flac", "size": 2}],
            },
            {
                "name": r"Music\Artist\Album Deluxe",
                "files": [{"filename": "03.flac", "size": 3}],
            },
        ]
        with patch.object(server, "slsk", return_value={"directories": dirs}):
            r = features.album_folder(server, "person", "Music/Artist/Album")
        self.assertEqual(len(r["files"]), 2)
        self.assertTrue(r["verifiedFolder"])
        self.assertTrue(all(f["username"] == "person" for f in r["files"]))
        self.assertEqual(len(r["artwork"]), 1)

    def test_album_artwork_keeps_nested_images_and_pdf_but_excludes_other_albums(self):
        dirs = [
            {
                "name": r"Music\Artist\Album",
                "files": [
                    {"filename": "01.flac", "size": 1},
                    {"filename": "01.mp3", "size": 2},
                    {"filename": "cover.jpg", "size": 3},
                    {"filename": "notes.txt", "size": 4},
                ],
            },
            {
                "name": r"Music\Artist\Album\Artwork",
                "files": [
                    {"filename": "back.PNG", "size": 5},
                    {"filename": "booklet.pdf", "size": 6},
                    {"filename": "run.exe", "size": 7},
                ],
            },
            {
                "name": r"Music\Artist\Album Deluxe",
                "files": [{"filename": "cover.jpg", "size": 8}],
            },
        ]
        with patch.object(server, "slsk", return_value=dirs):
            r = features.album_folder(server, "person", "Music/Artist/Album")
        self.assertEqual(len(r["files"]), 2)
        self.assertEqual(len(r["artwork"]), 3)
        self.assertEqual(r["totalFiles"], 7)
        self.assertTrue(all("Album Deluxe" not in f["filename"] for f in r["artwork"]))

    def test_album_download_batch_preserves_artwork_subfolder(self):
        file = {
            "username": "person",
            "filename": r"Music\Artist\Album\Artwork\back.png",
            "size": 123,
        }
        with patch.object(
            server, "slsk", return_value={"batch": {"id": "test"}, "failures": []}
        ) as remote:
            r = server.queue_file(file, "artist album", album_root=r"Music\Artist\Album")
        self.assertEqual(remote.call_args.args[0], "transfers/downloads/batches")
        self.assertEqual(remote.call_args.args[2]["options"]["destination"], "Album/Artwork")
        self.assertEqual(r["status"], "Queued")

    def test_album_batch_rejects_outside_paths_and_failed_enqueue(self):
        file = {
            "username": "person",
            "filename": r"Music\Artist\Other\back.png",
            "size": 123,
        }
        with patch.object(server, "slsk") as remote:
            with self.assertRaises(ValueError):
                server.queue_file(file, "album", album_root=r"Music\Artist\Album")
            remote.assert_not_called()
        with patch.object(
            server, "slsk", return_value={"failures": [{"filename": file["filename"]}]}
        ):
            self.assertEqual(
                server.queue_file(file, "album", album_root=r"Music\Artist\Other")["status"],
                "Unconfirmed",
            )
        with server.db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM requests").fetchone()[0], 1)

    def test_block_persists_and_cancels_only_target_uploads(self):
        with patch.object(server, "slsk", side_effect=self.upstream) as remote:
            r = features.control_update(server, {"action": "block", "username": "blocked"})
        self.assertEqual(r["cancelled"], 1)
        self.assertIn("existing", r["blockedUsers"])
        self.assertIn("blocked", r["blockedUsers"])
        self.assertIn(
            ("transfers/uploads/blocked/a", "DELETE"),
            [(x.args[0], x.args[1]) for x in remote.call_args_list if len(x.args) > 1],
        )
        c = yaml.safe_load(self.path.read_text())
        self.assertEqual(c["soulseek"]["password"], "keep-me")
        self.assertEqual(c["web"], self.config["web"])
        self.assertTrue(any((server.DATA / "config-backups").glob("*.yml")))

    def test_pause_and_resume_preserve_shared_folders(self):
        with patch.object(server, "slsk", side_effect=self.upstream):
            paused = features.control_update(server, {"action": "pause"})
            self.assertTrue(paused["paused"])
            self.assertEqual(paused["directories"], [])
            resumed = features.control_update(server, {"action": "resume"})
            self.assertFalse(resumed["paused"])
            self.assertEqual(resumed["directories"], [self.tmp.name])

    def test_invalid_folder_does_not_change_config(self):
        before = self.path.read_text()
        with self.assertRaises(ValueError):
            features.control_update(
                server, {"action": "folders", "directories": ["not-an-absolute-path"]}
            )
        self.assertEqual(self.path.read_text(), before)

    def test_config_secrets_not_returned(self):
        state = features.control_state(server)
        self.assertNotIn("keep-me", json.dumps(state))
        self.assertNotIn("keep-key", json.dumps(state))

    def test_chat_serializes_string_and_encodes_username(self):
        class H:
            def send_json(self, value):
                self.value = value

        h = H()
        with patch.object(server, "slsk", side_effect=self.upstream) as remote:
            features.post_route(
                h,
                "/api/send-message",
                {"username": "user/name", "message": "Hello"},
                server,
            )
        self.assertEqual(remote.call_args.args, ("conversations/user%2Fname", "POST", "Hello"))
        self.assertEqual(h.value, {"ok": True})

    def test_blank_chat_message_is_rejected(self):
        with self.assertRaises(ValueError):
            features.post_route(
                None,
                "/api/send-message",
                {"username": "person", "message": "   "},
                server,
            )


if __name__ == "__main__":
    unittest.main()
