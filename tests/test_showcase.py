import io, json, tempfile, unittest, time
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server, features, new_releases as n, release_sources as sources, release_details as details, showcase_data as data

URL = "https://www.allmusic.com/album/test-mw1"
ART = "https://fastly-s3.allmusic.com/release/example/front/400/cover.jpg"


def html(name="Example", artist="Artist", user=False):
    album = {
        "@type": "MusicAlbum",
        "name": name,
        "url": URL,
        "image": ART,
        "byArtist": {"name": artist},
        "genre": ["Jazz"],
        "track": [{"name": "Opening", "position": 1, "duration": "PT3M20S"}],
    }
    review = {
        "@type": "Review",
        "itemReviewed": {"@id": URL},
        "author": {"name": "A reader" if user else "AllMusic"},
        "reviewRating": {"ratingValue": 8, "bestRating": 10},
        "reviewBody": " ".join("word" + str(i) for i in range(120)),
    }
    return '<script type="application/ld+json">' + json.dumps([album, review]) + "</script>"


class ShowcaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = server.DATA
        server.DATA = Path(self.tmp.name)
        server.init()
        n.init(server)
        features.store_settings(server, {"discoveryOnline": True})
        today = n.date.today().isoformat()
        self.item = {
            "id": "test",
            "kind": n.KINDS["country"],
            "artist": "Artist",
            "album": "Example",
            "releaseDate": today,
            "country": "GB",
            "eventCountry": "GB",
            "releaseType": "Album",
            "source": "AllMusic",
            "sources": [{"name": "AllMusic", "url": URL}],
            "url": URL,
            "genres": ["Jazz"],
            "reason": "New release",
        }
        n.store(server, self.item.copy())

    def tearDown(self):
        server.DATA = self.old
        server.diag.close()
        self.tmp.cleanup()

    def test_safe_artwork_rejects_untrusted_and_placeholder_images(self):
        self.assertEqual(data.image_url(ART), ART)
        for bad in (
            "javascript:alert(1)",
            "http://fastly-s3.allmusic.com/test.jpg",
            "https://evil.test/cover.jpg",
            "https://allmusic.com.evil.test/a.jpg",
            "https://fastly-s3.allmusic.com/no_image/a.jpg",
        ):
            self.assertEqual(data.image_url(bad), "")

    def test_review_is_short_attributed_and_not_an_audience_score(self):
        record = details.parse(html(), self.item, URL)
        self.assertEqual(record["ratings"][0]["value"], 8)
        self.assertEqual(record["ratings"][0]["best"], 10)
        self.assertEqual(record["ratings"][0]["kind"], "critic")
        self.assertEqual(len(record["excerpt"].split()), 80)
        self.assertEqual(len(record["tracks"]), 1)
        reader = details.parse(html(user=True), self.item, URL)
        self.assertFalse(reader["ratings"])
        self.assertFalse(reader["excerpt"])

    def test_wrong_album_and_artist_are_rejected(self):
        for text in (html(name="Other"), html(artist="Namesake")):
            with self.assertRaises(ValueError):
                details.parse(text, self.item, URL)

    def test_publisher_description_is_a_short_quote_not_a_review_score(self):
        text = '<meta property="og:title" content="Example"><meta property="og:description" content="This album has a release description from its publisher.">'
        record = details.parse(text, self.item, "https://www.officialcharts.com/albums/example/")
        self.assertEqual(record["publisher"], "Official Charts")
        self.assertTrue(record["excerpt"])
        self.assertFalse(record["ratings"])

    def test_detail_pages_reject_arbitrary_urls_before_network(self):
        with patch.object(details, "urlopen") as network:
            with self.assertRaises(ValueError):
                details.page(server, "https://127.0.0.1/admin", self.item)
        network.assert_not_called()

    def test_dossier_enrichment_is_cached_and_retains_feedback(self):
        with server.db() as c:
            c.execute("INSERT INTO discovery_feedback VALUES (?,?)", ("test", "saved"))

        class Response(io.BytesIO):
            def geturl(self):
                return URL

        with patch.object(details, "urlopen", return_value=Response(html().encode())) as network:
            first = details.dossier(server, "test")
            second = details.dossier(server, "test")
        self.assertEqual(network.call_count, 1)
        self.assertEqual(first["item"]["feedback"], "saved")
        self.assertEqual(second["item"]["artwork"], ART)
        features.store_settings(server, {"discoveryOnline": False})
        with patch.object(details, "urlopen") as network:
            cached = details.dossier(server, "test")
        network.assert_not_called()
        self.assertEqual(cached["item"]["ratings"][0]["value"], 8)

    def test_failure_retains_release_and_original_links(self):
        with patch.object(details, "urlopen", side_effect=OSError("offline")):
            record = details.dossier(server, "test")
        self.assertEqual(record["item"]["album"], "Example")
        self.assertTrue(record["warnings"])
        self.assertFalse(record["publications"])

    def test_full_dataset_search_focus_and_sort_happen_before_paging(self):
        for i in range(55):
            n.store(
                server,
                {
                    **self.item,
                    "id": str(i),
                    "album": f"Record {i:03d}",
                    "ratings": [
                        {
                            "value": i % 10,
                            "best": 10,
                            "publisher": "AllMusic",
                            "kind": "critic",
                            "url": URL,
                        }
                    ],
                    "reason": "Listing",
                },
            )
        with server.db() as c:
            c.execute("INSERT INTO discovery_feedback VALUES (?,?)", ("4", "saved"))
        feed = n.snapshot(server, {"section": "country", "q": "Record 004"})
        self.assertEqual(feed["total"], 1)
        self.assertEqual(feed["items"][0]["id"], "4")
        saved = n.snapshot(server, {"section": "country", "focus": "saved"})
        self.assertEqual(saved["total"], 1)
        ranked = n.snapshot(server, {"section": "country", "sort": "rating", "limit": 1})
        self.assertEqual(ranked["items"][0]["ratings"][0]["value"], 9)
        reviewed = n.snapshot(server, {"section": "country", "focus": "reviewed", "offset": 48})
        self.assertEqual(reviewed["total"], 55)
        self.assertEqual(len(reviewed["items"]), 7)

    def test_new_filters_are_validated_and_do_not_change_archive_identity(self):
        options = n.filters(server, {})
        self.assertEqual(
            n.feed_key("country", options),
            n.feed_key("country", {**options, "q": "Jazz", "sort": "rating", "focus": "saved"}),
        )
        for body in ({"q": "x" * 201}, {"sort": "bad"}, {"focus": "bad"}):
            with self.assertRaises(ValueError):
                n.filters(server, body)

    def test_structured_rating_requires_an_explicit_scale(self):
        self.assertIsNone(data.score({"ratingValue": 8}, "Publisher", URL))
        self.assertIsNone(data.score({"ratingValue": 11, "bestRating": 10}, "Publisher", URL))

    def test_list_metadata_contains_artwork_and_a_labelled_critic_score(self):
        text = (
            '<h1 data-startweek="20261030">New</h1><article class="newReleaseItem"><div class="artist">Artist</div><h2 class="title"><a href="'
            + URL
            + '">Example</a></h2><div class="genres"><a>Jazz</a></div></article>'
        )
        obj = {
            "@type": "MusicAlbum",
            "url": URL,
            "name": "Example",
            "image": ART,
            "review": {
                "author": {"name": "A critic"},
                "reviewRating": {"ratingValue": 8, "bestRating": 10},
            },
        }
        row = sources.allmusic(
            text + '<script type="application/ld+json">' + json.dumps(obj) + "</script>"
        )[0]
        self.assertEqual(row["artwork"], ART)
        self.assertEqual(row["ratings"][0]["publisher"], "AllMusic")
        self.assertEqual(row["reviewAuthor"], "A critic")

    def test_repeated_schema_album_references_do_not_erase_the_critic_score(self):
        obj = {
            "@type": "MusicAlbum",
            "name": "Example",
            "url": URL,
            "review": {"reviewRating": {"ratingValue": 8, "bestRating": 10}},
        }
        reference = {"@type": "MusicAlbum", "name": "Example", "url": URL}
        records = data.album_metadata(
            '<script type="application/ld+json">' + json.dumps([obj, reference]) + "</script>"
        )
        self.assertEqual(records[URL]["ratings"][0]["value"], 8)

    def test_unknown_release_and_detail_route(self):
        with self.assertRaises(ValueError):
            details.dossier(server, "unknown")

        class Handler:
            def send_json(self, value):
                self.value = value

        h = Handler()
        with patch.object(
            details,
            "page",
            return_value={"publisher": "AllMusic", "url": URL, "tracks": []},
        ):
            self.assertTrue(
                n.get_route(h, "/api/discovery/releases/detail", {"id": ["test"]}, server)
            )
        self.assertEqual(h.value["item"]["id"], "test")


if __name__ == "__main__":
    unittest.main()
