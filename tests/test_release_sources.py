import io, json, tempfile, unittest, time, threading
from pathlib import Path
from datetime import date
from urllib.error import HTTPError
from urllib.request import urlopen
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server, features, discovery as d, new_releases as n, release_sources as p

CHARTS = """<section label="New Music Friday album releases - October 23 2026"><div class="chart-item"><a class="chart-name" href="/albums/example/fresh/">Fresh</a><a class="chart-artist">Example Artist</a></div></section><section label="New Music Friday song releases - October 23 2026"><div class="chart-item"><a class="chart-name" href="/songs/example/single/">Song</a><a class="chart-artist">Example Artist</a></div></section>"""
ALLMUSIC = """<h1 data-startweek="20261023">Featured</h1><article class="newReleaseItem"><div class="artist"><a>Example Artist</a></div><h2 class="title"><a href="https://www.allmusic.com/album/fresh-mw1">Fresh</a></h2><div class="genres"><a>Jazz</a></div></article>"""
APPLE = json.dumps(
    {
        "results": [
            {
                "wrapperType": "collection",
                "artistId": 1,
                "artistName": "Example Artist",
                "collectionName": "Fresh",
                "releaseDate": "2026-10-23T07:00:00Z",
                "primaryGenreName": "Jazz",
                "collectionViewUrl": "https://music.apple.com/gb/album/fresh/1",
            }
        ]
    }
)


class Response(io.BytesIO):
    def __init__(self, text, url):
        super().__init__(text.encode())
        self.url = url

    def geturl(self):
        return self.url


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = server.DATA
        server.DATA = Path(self.tmp.name)
        server.init()
        n.init(server)
        features.store_settings(server, {"discoveryOnline": True})
        d.job.update(
            running=False,
            cancel=False,
            warnings=[],
            errors=[],
            candidates=[],
            retryAt=0,
        )
        d.last_fetch.clear()
        d.service_cooldowns.clear()
        self.clock = patch.object(
            n,
            "window",
            side_effect=lambda days, today=None: (
                date(2026, 10, 25) - n.timedelta(days=days - 1),
                date(2026, 10, 25),
            ),
        )
        self.clock.start()

    def tearDown(self):
        self.clock.stop()
        server.DATA = self.old
        server.diag.close()
        self.tmp.cleanup()

    def library(self, count=1):
        with server.db() as c:
            for i in range(count):
                c.execute(
                    "INSERT INTO tracks VALUES (?,?,?,?,?,?,?,?)",
                    (
                        str(i),
                        "root",
                        "Example Artist" if i == 0 else "Artist " + str(i),
                        "Existing",
                        "Title",
                        1,
                        "flac",
                        1,
                    ),
                )

    def mock_response(self, request, **kwargs):
        url = request.full_url
        return Response(
            (
                '<a href="/chart-news/new-music-friday-23-october-2026/">New Music Friday</a>'
                if "/news/new-releases/" in url
                else (
                    CHARTS
                    if "officialcharts.com" in url
                    else ALLMUSIC if url == p.ALLMUSIC else APPLE
                )
            ),
            url,
        )

    def test_official_charts_parses_release_lists_not_top_chart(self):
        rows = p.charts(
            CHARTS
            + '<section label="Official Albums Chart"><div class="chart-item"><a class="chart-name">Old hit</a></div></section>'
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["releaseType"] for r in rows}, {"Album", "Single"})
        self.assertTrue(all(r["market"] == "GB" for r in rows))
        with self.assertRaises(ValueError):
            p.charts("<html>Site Unavailable</html>")

    def test_allmusic_has_genres_and_listing_date_not_claimed_original_date(self):
        row = p.allmusic(ALLMUSIC)[0]
        self.assertEqual(row["genres"], ["Jazz"])
        self.assertEqual(row["dateBasis"], "listing-week")
        self.assertEqual(row["market"], "unverified")

    def test_newsletter_fallback_uses_album_links_not_review_prose(self):
        xml = '<rss><channel><item><title>Week of 2026-10-23</title><description><![CDATA[<ul><li><a href="https://www.allmusic.com/artist/a">Artist</a> - <a href="https://www.allmusic.com/album/b">Album</a><br>Ignored review</li></ul>]]></description></item></channel></rss>'
        row = p.newsletter(xml)[0]
        self.assertEqual(row["album"], "Album")
        self.assertEqual(row["artist"], "Artist")
        self.assertFalse(row["genres"])
        with self.assertRaises(ValueError):
            p.newsletter("<!DOCTYPE rss><rss/>")

    def test_default_country_check_never_calls_musicbrainz_or_reads_artists(self):
        options = n.filters(server, {"country": "GB", "days": 7})
        with (
            patch.object(p, "urlopen", side_effect=self.mock_response) as network,
            patch.object(n, "request", side_effect=AssertionError("MusicBrainz used")),
            patch.object(n, "library_artists", side_effect=AssertionError("Library used")),
        ):
            meta = {}
            p.check(server, n, "country", options, meta)
        self.assertTrue(meta["complete"])
        self.assertEqual(network.call_count, 2)
        feed = n.snapshot(server, {"section": "country"})
        self.assertEqual(feed["total"], 1)
        self.assertEqual(feed["items"][0]["genres"], ["Jazz"])
        self.assertEqual(len(feed["items"][0]["sources"]), 2)
        self.assertEqual(feed["items"][0]["classification"], "original-date-unconfirmed")

    def test_default_library_match_checks_every_artist_locally(self):
        self.library(63)
        with (
            patch.object(p, "urlopen", side_effect=self.mock_response) as network,
            patch.object(n, "request", side_effect=AssertionError("MusicBrainz used")),
        ):
            meta = {}
            p.check(server, n, "library", n.filters(server, {"days": 7}), meta)
        self.assertEqual(network.call_count, 2)
        self.assertEqual(meta["checkedArtists"], 63)
        self.assertEqual(n.snapshot(server, {"section": "library"})["total"], 1)

    def test_cache_avoids_network_and_invalid_responses_do_not_overwrite_it(self):
        with patch.object(p, "urlopen", side_effect=self.mock_response) as network:
            first = p.fetch(server, p.CHARTS, p.charts)
            second = p.fetch(server, p.CHARTS, p.charts)
        self.assertEqual(network.call_count, 1)
        self.assertEqual(first, second)
        with server.db() as c:
            c.execute("UPDATE discovery_cache SET updated=?", (time.time() - 86400,))
        with patch.object(
            p,
            "urlopen",
            return_value=Response("<html>Site unavailable</html>", p.CHARTS),
        ):
            stale = p.fetch(server, p.CHARTS, p.charts)
        self.assertEqual(first, stale)
        self.assertTrue(any("cached" in warning for warning in d.job["warnings"]))
        with server.db() as c:
            self.assertEqual(
                json.loads(c.execute("SELECT value FROM discovery_cache").fetchone()[0]),
                first,
            )

    def test_source_failure_keeps_other_supplier_and_no_musicbrainz_fallback(self):
        def network(request, **kwargs):
            if request.full_url == p.CHARTS:
                raise HTTPError(p.CHARTS, 503, "Busy", {}, None)
            return self.mock_response(request, **kwargs)

        with (
            patch.object(p, "urlopen", side_effect=network),
            patch.object(n, "request", side_effect=AssertionError("MusicBrainz fallback")),
        ):
            rows = p.listings(server, "GB")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["market"], "unverified")
        self.assertTrue(d.job["warnings"])

    def test_other_countries_are_never_misrepresented_as_uk(self):
        with patch.object(p, "urlopen", side_effect=self.mock_response):
            p.check(server, n, "country", n.filters(server, {"country": "LU"}), {})
        row = n.snapshot(server, {"section": "country", "country": "LU"})["items"][0]
        self.assertFalse(row["marketVerified"])
        self.assertEqual(row["eventCountry"], "UNVERIFIED")
        self.assertEqual(
            n.snapshot(server, {"section": "country", "country": "LU", "worldwide": False})[
                "total"
            ],
            0,
        )

    def test_apple_lookup_does_not_require_musicbrainz_identity_and_rejects_namesakes(
        self,
    ):
        with patch.object(p, "urlopen", side_effect=self.mock_response):
            rows = p.artist_albums(server, "Example Artist", "GB")
        self.assertEqual(rows[0]["genres"], ["Jazz"])
        self.assertEqual(rows[0]["dateBasis"], "catalogue-date")
        variants = json.loads(APPLE)["results"]
        variants.append({**variants[0], "artistId": 2})
        with patch.object(p, "fetch", return_value=variants):
            self.assertEqual(p.artist_albums(server, "Example Artist", "GB"), [])

    def test_deep_artist_checks_are_bounded_resumable_and_restart_after_library_change(
        self,
    ):
        self.library(23)
        meta = {}
        options = {**n.filters(server, {}), "artistLookup": True}
        with patch.object(p, "artist_albums", return_value=[]) as lookup:
            p.check(server, n, "library", options, meta)
            self.assertEqual(lookup.call_count, 10)
            self.assertEqual(meta["artistOffset"], 10)
            p.check(server, n, "library", options, meta, True)
            self.assertEqual(meta["artistOffset"], 20)
            p.check(server, n, "library", options, meta, True)
            self.assertEqual(meta["artistOffset"], 23)
            self.assertFalse(meta["hasMore"])
            with server.db() as c:
                c.execute("DELETE FROM tracks WHERE path='1'")
            p.check(server, n, "library", options, meta, True)
            self.assertEqual(meta["artistOffset"], 10)

    def test_rate_limit_is_not_retried_and_cooldown_preserves_cache(self):
        err = HTTPError(p.APPLE, 429, "limited", {"Retry-After": "120"}, None)
        with patch.object(p, "urlopen", side_effect=err) as network:
            for _ in range(2):
                with self.assertRaises(ValueError):
                    p.fetch(server, p.APPLE, p.apple_rows)
        self.assertEqual(network.call_count, 1)
        self.assertGreater(d.service_cooldowns["itunes.apple.com"], time.time() + 100)

    def test_cancellation_prevents_further_supplier_requests(self):
        d.job["cancel"] = True
        with patch.object(p, "urlopen") as network:
            self.assertEqual(p.listings(server, "GB"), [])
        network.assert_not_called()

    def test_real_http_default_start_uses_alternatives(self):
        from urllib.request import Request

        host = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=host.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:" + str(host.server_port)
        try:
            with (
                patch.object(p, "urlopen", side_effect=self.mock_response),
                patch.object(n, "request", side_effect=AssertionError("MusicBrainz used")),
            ):
                request = Request(
                    base + "/api/discovery/releases/start",
                    data=b'{"section":"country","country":"GB"}',
                    headers={
                        "Content-Type": "application/json",
                        "X-Resonance-Token": server.TOKEN,
                    },
                )
                with urlopen(request, timeout=3) as response:
                    self.assertTrue(json.load(response)["running"])
                deadline = time.monotonic() + 3
                while d.job["running"] and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertFalse(d.job["running"])
                with urlopen(
                    base + "/api/discovery/releases?section=country&country=GB",
                    timeout=3,
                ) as response:
                    feed = json.load(response)
            self.assertEqual(feed["total"], 1)
            self.assertEqual(feed["check"]["provider"], "independent")
        finally:
            host.shutdown()
            host.server_close()

    def test_archive_dates_support_both_url_orders_and_reject_unrelated_links(self):
        text = '<a href="/chart-news/new-music-friday-11-september-2026/">September</a><a href="/chart-news/new-music-friday-october-30-2026/">October</a><a href="https://evil.test/chart-news/new-music-friday-october-23-2026/">Bad</a>'
        rows = p.archive_index(text)
        self.assertEqual([r["date"] for r in rows], ["2026-10-30", "2026-09-11"])
        self.assertEqual(len(rows), 2)

    def test_september_release_is_backfilled_for_both_tabs_and_excluded_from_thirty_days(
        self,
    ):
        self.library()
        with server.db() as c:
            c.execute("UPDATE tracks SET artist='Bloc Party'")
        first = date(2026, 8, 7)
        days = [first + n.timedelta(days=7 * i) for i in range(13)]

        def url(day):
            return (
                "https://www.officialcharts.com/chart-news/new-music-friday-"
                + day.strftime("%d-%B-%Y").lower()
                + "/"
            )

        def page(day):
            artist = "BLOC PARTY" if day == date(2026, 9, 11) else "Example Artist"
            album = (
                "ANATOMY OF A BRIEF ROMANCE"
                if day == date(2026, 9, 11)
                else "Album " + day.isoformat()
            )
            return (
                '<section label="New Music Friday album releases - '
                + day.strftime("%B %d %Y")
                + '"><div class="chart-item"><a class="chart-name" href="/albums/example/">'
                + album
                + '</a><a class="chart-artist">'
                + artist
                + "</a></div></section>"
            )

        index = "".join('<a href="' + url(day) + '">New Music Friday</a>' for day in days)
        urls = {url(day): page(day) for day in days}
        urls[p.CHARTS] = page(days[-1])
        urls[p.ARCHIVE] = index
        calls = []

        def network(request, **kwargs):
            calls.append(request.full_url)
            return Response(urls[request.full_url], request.full_url)

        with (
            patch.object(
                n,
                "window",
                side_effect=lambda count, today=None: (
                    date(2026, 10, 30) - n.timedelta(days=count - 1),
                    date(2026, 10, 30),
                ),
            ),
            patch.object(p, "urlopen", side_effect=network),
            patch.object(d, "wait_for_retry"),
            patch.object(n, "request", side_effect=AssertionError("MusicBrainz used")),
        ):
            options = n.filters(server, {"days": 90, "country": "GB", "worldwide": False})
            meta = {}
            p.check(server, n, "country", options, meta)
            self.assertEqual(meta["archiveWeeksImported"], 13)
            self.assertFalse(meta["archiveMissingWeeks"])
            self.assertTrue(meta["complete"])
            self.assertIn(url(date(2026, 9, 11)), calls)
            feed = n.snapshot(server, {"section": "country", **options})
            self.assertTrue(any("ANATOMY" in r["album"] for r in feed["items"]))
            self.assertFalse(
                any(
                    "ANATOMY" in r["album"]
                    for r in n.snapshot(server, {"section": "country", **options, "days": 30})[
                        "items"
                    ]
                )
            )
            # AllMusic may be fetched by library mode; return a valid current page without adding unrelated items.
            urls[p.ALLMUSIC] = ALLMUSIC
            before = len(calls)
            p.check(server, n, "library", options, {})
            library = n.snapshot(server, {"section": "library", **options})
            self.assertEqual(len(library["items"]), 1)
            self.assertIn("ANATOMY", library["items"][0]["album"])
            self.assertEqual(library["items"][0]["matchedArtists"], ["Bloc Party"])
            self.assertEqual(
                len(calls) - before,
                1,
                "archive pages must be shared from cache across both tabs",
            )

    def test_missing_archive_week_is_reported_and_current_results_survive(self):
        def fetch(s, url, parser, **kwargs):
            if url == p.CHARTS:
                return p.charts(CHARTS)
            if "/news/new-releases/" in url:
                return [{"date": "2026-10-16", "url": p.CHARTS + "older"}]
            raise ValueError("Archive temporarily unavailable")

        with patch.object(p, "fetch", side_effect=fetch):
            meta = {}
            p.check(
                server,
                n,
                "country",
                n.filters(server, {"days": 30, "worldwide": False}),
                meta,
            )
        self.assertFalse(meta["complete"])
        self.assertIn("2026-10-16", meta["archiveMissingWeeks"])
        self.assertEqual(n.snapshot(server, {"section": "country"})["total"], 1)


if __name__ == "__main__":
    unittest.main()
