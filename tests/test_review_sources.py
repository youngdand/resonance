import json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import review_sources as r, server, features, new_releases as n

ITEM = {"artist": "The Big Moon", "album": "Forever"}
FEED = "<rss><channel><item><title>The Big Moon: Forever review</title><link>https://www.theguardian.com/music/review</link><description>&lt;p&gt;A strong record.&lt;/p&gt;</description></item></channel></rss>"
URL = r.SOURCES[2][1]


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = server.DATA
        server.DATA = Path(self.tmp.name)
        server.init()
        n.init(server)
        features.store_settings(server, {"discoveryOnline": True})
        r.init(server)

    def tearDown(self):
        server.DATA = self.old
        server.diag.close()
        self.tmp.cleanup()

    def test_feed_whole_phrase_matching(self):
        rows = r.parse_index(FEED, URL, "feed")
        self.assertEqual(len(rows), 1)
        self.assertTrue(r.matches(rows[0], ITEM))
        self.assertFalse(r.matches(rows[0], {**ITEM, "album": "Ever"}))
        self.assertFalse(r.matches(rows[0], {**ITEM, "artist": "Other"}))
        self.assertNotIn("<p>", rows[0]["excerpt"])

    def test_feed_rejects_external_links_and_entities(self):
        self.assertFalse(
            r.parse_index(
                FEED.replace(
                    "https://www.theguardian.com/music/review",
                    "https://127.0.0.1/private",
                ),
                URL,
                "feed",
            )
        )
        for raw in ("<!DOCTYPE rss><rss/>", '<!ENTITY e "secret"><rss/>', "<html/>"):
            with self.assertRaises(ValueError):
                r.parse_index(raw, URL, "feed")

    def test_indie_and_pitchfork(self):
        rows = r.parse_index(
            '<a href="/the-big-moon-forever-review/">The Big Moon’s Forever: A new chapter</a>',
            r.SOURCES[4][1],
            "index",
        )
        self.assertTrue(r.matches(rows[0], ITEM))
        raw = (
            '<script type="application/ld+json">'
            + json.dumps(
                {
                    "@type": "ListItem",
                    "name": "Forever",
                    "url": "https://pitchfork.com/reviews/albums/the-big-moon-forever/",
                }
            )
            + "</script>"
        )
        rows = r.parse_index(raw, r.SOURCES[0][1], "index")
        self.assertTrue(r.matches(rows[0], ITEM))
        self.assertFalse(r.matches(rows[0], {**ITEM, "artist": "Namesake"}))

    def test_explicit_rating_and_bounded_excerpt(self):
        raw = (
            '<script type="application/ld+json">'
            + json.dumps(
                {
                    "@type": "MusicReview",
                    "author": {"name": "A Writer"},
                    "reviewBody": " ".join(["word"] * 120),
                    "reviewRating": {"ratingValue": 4, "bestRating": 5},
                }
            )
            + "</script>"
        )
        pub = r.article(raw, {"url": "https://www.theguardian.com/music/review"}, "The Guardian")
        self.assertEqual(pub["ratings"][0]["value"], 4)
        self.assertEqual(len(pub["excerpt"].split()), 80)
        self.assertEqual(pub["author"], "A Writer")

    def test_audience_scores_and_missing_scales_not_adopted(self):
        for obj in (
            {"@type": "AggregateRating", "ratingValue": 9, "bestRating": 10},
            {"@type": "Review", "reviewRating": {"ratingValue": 4}},
        ):
            pub = r.article(
                '<script type="application/ld+json">' + json.dumps(obj) + "</script>",
                {"url": "https://www.theguardian.com/music/review"},
                "The Guardian",
            )
            self.assertFalse(pub["ratings"])

    def test_shared_cache_failures_and_links(self):
        def fetch(url, version):
            if url == URL:
                return FEED
            if url == "https://www.theguardian.com/music/review":
                return '<meta property="og:description" content="A review">'
            raise OSError("blocked")

        with patch.object(r, "fetch", side_effect=fetch) as network:
            result = r.lookup(server, ITEM)
            count = network.call_count
            again = r.lookup(server, ITEM)
            self.assertEqual(network.call_count, count)
        self.assertEqual(len(result["reviewSources"]), 13)
        self.assertEqual(len(result["publications"]), 1)
        self.assertEqual(result["publications"][0]["publisher"], "The Guardian")
        self.assertTrue(any("unavailable" in x["status"] for x in result["reviewSources"]))
        self.assertEqual(again["publications"], result["publications"])

    def test_offline_uses_cache_without_network(self):
        r.cached(server, "test", lambda: {"rows": [1], "status": "Cached"})
        with server.db() as c:
            c.execute("UPDATE review_source_cache SET updated=0")
        features.store_settings(server, {"discoveryOnline": False})
        with patch.object(r, "fetch") as network:
            self.assertTrue(r.cached(server, "test", lambda: self.fail())["stale"])
            result = r.lookup(server, ITEM)
        network.assert_not_called()
        self.assertEqual(len(result["reviewSources"]), 13)

    def test_redirect_allowlist(self):
        for bad in (
            "http://www.theguardian.com/a",
            "https://evil.test/a",
            "https://www.theguardian.com.evil.test/a",
            "https://user@www.theguardian.com/a",
            "https://www.theguardian.com:8000/a",
        ):
            self.assertFalse(r.allowed(bad, URL))

    def test_failed_refresh_retains_stale_index_and_backs_off(self):
        r.cached(
            server,
            "index:" + URL,
            lambda: {"rows": [{"title": "Old"}], "status": "Recent index checked"},
        )
        with server.db() as c:
            c.execute("UPDATE review_source_cache SET updated=0")
        loader = __import__("unittest.mock", fromlist=["Mock"]).Mock(side_effect=OSError("blocked"))
        first = r.cached(server, "index:" + URL, loader)
        second = r.cached(server, "index:" + URL, loader)
        self.assertEqual(loader.call_count, 1)
        self.assertTrue(first["stale"])
        self.assertEqual(first["rows"], second["rows"])

    def test_review_endpoint_persists_scores_and_preserves_feedback(self):
        with server.db() as c:
            c.execute(
                "INSERT INTO discovery_items VALUES (?,?)",
                (
                    "release",
                    json.dumps(
                        {
                            "id": "release",
                            "kind": n.KINDS["country"],
                            **ITEM,
                            "ratings": [],
                        }
                    ),
                ),
            )
        with server.db() as c:
            c.execute("INSERT INTO discovery_feedback VALUES (?,?)", ("release", "saved"))
        result = {
            "publications": [
                {
                    "ratings": [
                        {
                            "publisher": "The Guardian",
                            "value": 4,
                            "best": 5,
                            "url": "https://www.theguardian.com/music/review",
                            "kind": "critic",
                        }
                    ]
                }
            ],
            "reviewSources": [],
        }

        class Handler:
            def send_json(self, value):
                self.value = value

        handler = Handler()
        with patch.object(r, "lookup", return_value=result):
            self.assertTrue(
                n.get_route(
                    handler,
                    "/api/discovery/releases/reviews",
                    {"id": ["release"]},
                    server,
                )
            )
        with server.db() as c:
            item = json.loads(
                c.execute("SELECT value FROM discovery_items WHERE id=?", ("release",)).fetchone()[
                    0
                ]
            )
            feedback = c.execute(
                "SELECT status FROM discovery_feedback WHERE id=?", ("release",)
            ).fetchone()[0]
        self.assertEqual(item["ratings"][0]["value"], 4)
        self.assertEqual(feedback, "saved")

    def test_publisher_search_matches_html_entities_and_older_album(self):
        raw = json.dumps(
            [
                {
                    "link": "https://www.clashmusic.com/reviews/radio-free-alice-whats-in-between/",
                    "title": {"rendered": "Radio Free Alice &#8211; What&#8217;s In Between"},
                    "excerpt": {"rendered": "<p>A vivid debut with plenty to discuss.</p>"},
                    "date": "2026-10-28",
                }
            ]
        )
        rows = r.search_index(raw, r.SEARCHES[1][1], "search-api")
        self.assertTrue(
            r.matches(rows[0], {"artist": "RADIO FREE ALICE", "album": "WHAT'S IN BETWEEN"})
        )
        self.assertNotIn("<p>", rows[0]["excerpt"])

    def test_targeted_search_finds_album_absent_from_recent_indexes(self):
        url = "https://www.clashmusic.com/reviews/radio-free-alice-whats-in-between/"

        def fetch(request, version):
            if "/wp-json/wp/v2/posts?" in request and "clashmusic.com" in request:
                return json.dumps(
                    [
                        {
                            "link": url,
                            "title": {"rendered": "Radio Free Alice – What's In Between"},
                            "excerpt": {"rendered": "A thoughtful review of the debut."},
                        }
                    ]
                )
            if request == url:
                return (
                    '<meta property="og:description" content="A thoughtful review of the debut.">'
                )
            raise OSError("not in index")

        with patch.object(r, "fetch", side_effect=fetch) as network:
            result = r.lookup(server, {"artist": "Radio Free Alice", "album": "What's In Between"})
            count = network.call_count
            r.lookup(server, {"artist": "Radio Free Alice", "album": "What's In Between"})
            self.assertEqual(network.call_count, count)
        self.assertEqual(result["publications"][0]["publisher"], "Clash")
        self.assertEqual(result["publications"][0]["kind"], "review")

    def test_article_without_schema_uses_article_paragraph_not_navigation(self):
        text = (
            "<nav><p>"
            + ("wrong " * 50)
            + '</p></nav><div class="postcontent"><p>'
            + ("review " * 110)
            + "</p></div>"
        )
        pub = r.article(text, {"url": "https://www.silentradio.co.uk/review/"}, "Silent Radio")
        self.assertEqual(len(pub["excerpt"].split()), 80)
        self.assertTrue(pub["excerpt"].startswith("review"))
        self.assertNotIn("wrong", pub["excerpt"])

    def test_release_context_is_album_specific_and_cached(self):
        import release_context

        item = {
            "artist": "Nines",
            "album": "Young Nina",
            "releaseDate": "2026-10-30",
            "sources": [{"url": "https://www.officialcharts.com/albums/nines-young-nina/"}],
        }
        paragraph = "Nines presents Young Nina, a mixtape from earlier in his career. It includes tracks with several collaborators and archive recordings from his youth."
        with patch.object(
            r,
            "fetch",
            return_value="<p>" + paragraph + "</p><p>Another unrelated album is out today.</p>",
        ) as network:
            result = release_context.lookup(server, item)
            release_context.lookup(server, item)
            self.assertEqual(network.call_count, 1)
        self.assertEqual(result[0]["kind"], "release-note")
        self.assertFalse(result[0]["review"])
        self.assertEqual(result[0]["excerpt"], paragraph)

    def test_unknown_release(self):
        with self.assertRaises(ValueError):
            r.for_release(server, "missing")


if __name__ == "__main__":
    unittest.main()
