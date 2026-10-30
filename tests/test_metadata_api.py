import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server, library_sync, realtime


class MetadataAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = server.DATA
        server.DATA = Path(self.tmp.name)
        server.init()
        self.page = {
            "revision": 12,
            "complete": True,
            "hasMore": False,
            "after": "Music/Artist/Album/01.flac",
            "items": [
                {
                    "artist": "Artist",
                    "album": "Album",
                    "title": "Cached title",
                    "duration": 180,
                    "file": {"filename": r"Music\Artist\Album\01.flac", "size": 100},
                }
            ],
        }

    def tearDown(self):
        server.DATA = self.old
        self.tmp.cleanup()

    def upstream(self, path, *args):
        if path == "shares":
            return {
                "local": [
                    {
                        "remotePath": "Music",
                        "localPath": str(Path(self.tmp.name) / "missing-music-root"),
                    }
                ]
            }
        if path == "application":
            return {"shares": {"ready": True, "scanning": False}}
        if path.startswith("shares/library?"):
            return self.page
        raise AssertionError("No local inventory fallback expected: " + path)

    def test_cached_tags_import_without_opening_music_or_reading_file_stats(self):
        with (
            patch.object(server, "slsk", side_effect=self.upstream),
            patch("pathlib.Path.stat", side_effect=AssertionError("must not stat music")),
        ):
            result = library_sync.metadata_inventory(server)
        self.assertEqual(result[0][0][2:5], ("Artist", "Album", "Cached title"))

    def test_version_change_does_not_replace_previous_collection(self):
        self.page.update(hasMore=True)
        calls = 0

        def upstream(path, *args):
            nonlocal calls
            if path.startswith("shares/library?"):
                calls += 1
                return {
                    **self.page,
                    "revision": 12 if calls == 1 else 13,
                    "hasMore": calls == 1,
                }
            return self.upstream(path, *args)

        with patch.object(server, "slsk", side_effect=upstream):
            with self.assertRaisesRegex(ValueError, "changed during"):
                library_sync.metadata_inventory(server)

    def test_unsupported_upstream_allows_legacy_fallback(self):
        def upstream(path, *args):
            if path.startswith("shares/library?"):
                raise server.UpstreamError("not found", status=404)
            return self.upstream(path, *args)

        with patch.object(server, "slsk", side_effect=upstream):
            self.assertIsNone(library_sync.metadata_inventory(server))

    def test_real_peer_error_does_not_trigger_inventory_fallback(self):
        def upstream(path, *args):
            if path.startswith("shares/library?"):
                raise server.UpstreamError("initializing", status=503, code="library_not_ready")
            return self.upstream(path, *args)

        with patch.object(server, "slsk", side_effect=upstream):
            with self.assertRaisesRegex(ValueError, "initializing"):
                library_sync.metadata_inventory(server)

    def test_unsafe_cache_path_is_rejected(self):
        self.page["items"][0]["file"]["filename"] = r"Music\..\outside.flac"
        with patch.object(server, "slsk", side_effect=self.upstream):
            with self.assertRaisesRegex(ValueError, "Unsafe path"):
                library_sync.metadata_inventory(server)

    def test_signalr_record_frames_and_keepalives(self):
        self.assertEqual(realtime.frames(b'{}\x1e{"type":6}\x1e'), [{}, {"type": 6}])


if __name__ == "__main__":
    unittest.main()
