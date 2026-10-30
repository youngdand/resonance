import json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server, features, new_releases as n, release_artwork as a, showcase_data as data

ART = "https://is1-ssl.mzstatic.com/image/test/100x100bb.jpg"
DZ = "https://cdn-images.dzcdn.net/images/cover/test/500x500.jpg"
ITEM = {
    "id": "test",
    "kind": n.KINDS["country"],
    "artist": "Example Artist",
    "album": "New Album",
    "releaseType": "Album",
    "country": "GB",
}


def apple(artist="Example Artist", album="New Album"):
    return {
        "results": [
            {
                "wrapperType": "collection",
                "artistName": artist,
                "collectionName": album,
                "artworkUrl100": ART,
                "collectionViewUrl": "https://music.apple.com/gb/album/new-album/123",
            }
        ]
    }


def deezer():
    return {
        "data": [
            {
                "artist": {"name": "Example Artist"},
                "title": "New Album",
                "cover_big": DZ,
                "link": "https://www.deezer.com/album/123",
            }
        ]
    }


class ArtworkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = server.DATA
        server.DATA = Path(self.tmp.name)
        server.init()
        n.init(server)
        features.store_settings(server, {"discoveryOnline": True})
        with server.db() as c:
            c.execute("INSERT INTO discovery_items VALUES (?,?)", ("test", json.dumps(ITEM)))

    def tearDown(self):
        server.DATA = self.old
        server.diag.close()
        self.tmp.cleanup()

    def test_identity_and_edition_must_match(self):
        self.assertTrue(a.apple(apple(), ITEM))
        for payload in (
            apple(artist="Other"),
            apple(album="New Album (Live)"),
            apple(album="New Album Deluxe"),
        ):
            self.assertFalse(a.apple(payload, ITEM))
        self.assertTrue(a.apple(apple(album="New Album - EP"), {**ITEM, "releaseType": "EP"}))
        self.assertFalse(a.apple(apple(album="New Album - EP"), ITEM))

    def test_image_objects_lazy_attributes_and_trusted_hosts(self):
        self.assertEqual(data.image_url({"contentUrl": ART}), ART)
        self.assertEqual(data.image_url(["https://bad.test/a.jpg", {"url": ART}]), ART)
        self.assertEqual(
            data.image_attrs({"src": "data:image/gif;base64,abc", "data-src": ART}), ART
        )
        self.assertEqual(data.image_attrs({"srcset": ART + " 100w, " + DZ + " 500w"}), DZ)
        for bad in (
            "https://dzcdn.net.evil.test/a.jpg",
            "https://user@is1-ssl.mzstatic.com/a.jpg",
            "https://is1-ssl.mzstatic.com:123/a.jpg",
        ):
            self.assertFalse(data.image_url(bad))

    def test_artwork_is_stored_with_store_link_and_cached_across_tabs(self):
        with server.db() as c:
            c.execute("INSERT INTO discovery_feedback VALUES (?,?)", ("test", "saved"))
            c.execute(
                "INSERT INTO discovery_items VALUES (?,?)",
                ("second", json.dumps({**ITEM, "id": "second"})),
            )
        with patch.object(a, "request", return_value=apple()) as net:
            result = a.find(server, "test")
            second = a.find(server, "second")
            self.assertEqual(net.call_count, 1)
        self.assertIn("/600x600bb.", result["artwork"])
        self.assertEqual(result["artworkSource"], "Apple Music")
        self.assertEqual(result["artworkSourceUrl"], second["artworkSourceUrl"])
        with server.db() as c:
            self.assertEqual(
                c.execute("SELECT status FROM discovery_feedback WHERE id=?", ("test",)).fetchone()[
                    0
                ],
                "saved",
            )

    def test_deezer_fallback_when_apple_missing(self):
        with patch.object(a, "request", side_effect=[{"results": []}, deezer()]) as net:
            result = a.find(server, "test")
        self.assertEqual(net.call_count, 2)
        self.assertEqual(result["artwork"], DZ)
        self.assertEqual(result["artworkSource"], "Deezer")

    def test_existing_publisher_cover_needs_no_search(self):
        with server.db() as c:
            c.execute(
                "UPDATE discovery_items SET value=? WHERE id=?",
                (json.dumps({**ITEM, "artwork": ART}), "test"),
            )
        with patch.object(a, "request") as net:
            self.assertEqual(a.find(server, "test")["artwork"], ART)
        net.assert_not_called()

    def test_broken_image_moves_to_next_supplier(self):
        with patch.object(a, "request", side_effect=[apple(), deezer()]):
            first = a.find(server, "test")
            second = a.find(server, "test", first["artwork"])
        self.assertEqual(second["artwork"], DZ)
        with patch.object(a, "request") as net:
            third = a.find(server, "test")
        self.assertEqual(third["artwork"], DZ)
        net.assert_not_called()

    def test_offline_does_not_request_metadata(self):
        features.store_settings(server, {"discoveryOnline": False})
        with patch.object(a, "request") as net:
            result = a.find(server, "test")
        net.assert_not_called()
        self.assertFalse(result["artwork"])

    def test_failures_are_cached_without_hiding_the_release(self):
        with patch.object(a, "request", side_effect=OSError("offline")) as net:
            one = a.find(server, "test")
            count = net.call_count
            two = a.find(server, "test")
            self.assertEqual(net.call_count, count)
        self.assertFalse(one["artwork"])
        self.assertEqual(one["id"], two["id"])

    def test_archive_only_uses_existing_valid_release_group_id(self):
        ident = "12345678-1234-1234-1234-123456789abc"
        with server.db() as c:
            c.execute(
                "UPDATE discovery_items SET value=? WHERE id=?",
                (json.dumps({**ITEM, "mbid": ident}), "test"),
            )
        record = {
            "images": [
                {
                    "front": True,
                    "approved": True,
                    "thumbnails": {"500": "http://coverartarchive.org/release/test/500.jpg"},
                }
            ]
        }
        with patch.object(a, "request", side_effect=[{"results": []}, {"data": []}, record]) as net:
            result = a.find(server, "test")
        self.assertEqual(net.call_count, 3)
        self.assertEqual(result["artworkSource"], "Cover Art Archive")
        self.assertTrue(result["artwork"].startswith("https://"))

    def test_route_and_release_refresh_keep_cached_artwork(self):
        class Handler:
            def send_json(self, value):
                self.value = value

        handler = Handler()
        with patch.object(a, "request", return_value=apple()):
            self.assertTrue(
                n.get_route(handler, "/api/discovery/releases/artwork", {"id": ["test"]}, server)
            )
        self.assertEqual(handler.value["artworkSource"], "Apple Music")
        n.store(
            server,
            {
                **ITEM,
                "artwork": "",
                "eventCountry": "GB",
                "releaseDate": "2026-10-30",
                "reason": "Refreshed release listing",
            },
        )
        with server.db() as c:
            item = json.loads(
                c.execute("SELECT value FROM discovery_items WHERE id=?", ("test",)).fetchone()[0]
            )
        self.assertEqual(item["artwork"], handler.value["artwork"])
        self.assertEqual(item["artworkSource"], "Apple Music")

    def test_unknown_release_rejected_without_network(self):
        with patch.object(a, "request") as net:
            with self.assertRaises(ValueError):
                a.find(server, "missing")
        net.assert_not_called()


if __name__ == "__main__":
    unittest.main()
