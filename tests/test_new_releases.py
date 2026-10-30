import json, tempfile, unittest, time
from pathlib import Path
from datetime import date
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server, discovery as d, new_releases as n, features

A = "11111111-1111-4111-8111-111111111111"
B = "22222222-2222-4222-8222-222222222222"
G = "33333333-3333-4333-8333-333333333333"
G2 = "44444444-4444-4444-8444-444444444444"
TODAY = date(2026, 10, 25)


class NewReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = server.DATA
        server.DATA = Path(self.tmp.name)
        server.init()
        n.init(server)
        features.store_settings(server, {"discoveryOnline": True})
        d.job.update(
            running=False,
            errors=[],
            warnings=[],
            candidates=[],
            cancel=False,
            retryAt=0,
        )
        self.clock = patch.object(
            n,
            "window",
            side_effect=lambda days, today=None: (
                TODAY - n.timedelta(days=days - 1),
                TODAY,
            ),
        )
        self.clock.start()
        self.options = n.filters(server, {})

    def tearDown(self):
        self.clock.stop()
        server.DATA = self.old
        server.diag.close()
        self.tmp.cleanup()

    def library(self, name="Example Artist"):
        with server.db() as c:
            c.execute(
                "INSERT OR REPLACE INTO tracks VALUES (?,?,?,?,?,?,?,?)",
                (name + ".flac", "root", name, "Old Album", "Song", 100, "flac", 1),
            )

    def match(self, name="Example Artist", ident=A):
        with server.db() as c:
            c.execute(
                "INSERT OR REPLACE INTO discovery_matches VALUES (?,?,?)",
                (server.norm(name), ident, name),
            )

    def group(self, day="2026-10-20", ident=G, artist=A, name="Example Artist"):
        return {
            "id": ident,
            "title": "New Album",
            "primary-type": "Album",
            "first-release-date": day,
            "artist-credit": [{"artist": {"id": artist, "name": name}}],
        }

    def edition(self, country="GB", day="2026-10-20", group=None):
        return {
            "id": G2,
            "title": "An edition",
            "status": "Official",
            "country": country,
            "date": day,
            "release-group": group or self.group(),
            "artist-credit": [{"artist": {"id": A, "name": "Example Artist"}}],
        }

    def check(self, section="country", options=None):
        meta = {}
        (
            n.country_check(server, options or self.options, meta)
            if section == "country"
            else n.library_check(server, options or self.options, meta)
        )
        return meta

    def test_window_is_inclusive_and_dates_are_not_guessed(self):
        begin, end = n.window(30)
        self.assertEqual(str(begin), "2026-09-26")
        self.assertEqual(str(end), "2026-10-25")
        self.assertTrue(n.in_window("2026-09-26", begin, end))
        self.assertFalse(n.in_window("2026-09-25", begin, end))
        self.assertFalse(n.in_window("2026-10-26", begin, end))
        self.assertIsNone(n.exact_date("2026-10"))

    def test_preferences_default_to_uk_and_accept_luxembourg(self):
        self.assertEqual(self.options["country"], "GB")
        self.assertEqual(n.filters(server, {"country": "LU"})["country"], "LU")
        self.assertEqual(len(n.COUNTRIES), 249)
        for invalid in (
            {"country": "XX"},
            {"days": 1},
            {"days": True},
            {"type": "bootleg"},
            {"worldwide": "false"},
        ):
            with self.assertRaises(ValueError):
                n.filters(server, invalid)

    def test_country_and_library_keys_are_separate_and_country_specific(self):
        self.assertNotEqual(
            n.feed_key("country", self.options), n.feed_key("library", self.options)
        )
        self.assertNotEqual(
            n.feed_key("country", self.options),
            n.feed_key("country", {**self.options, "country": "LU"}),
        )

    def test_artist_check_includes_recent_verified_artist_and_ignores_reissues_future_and_namesakes(
        self,
    ):
        self.library()
        self.match()
        rows = [
            self.group(),
            self.group("1995-10-20", G2),
            self.group("2026-10-26", G2),
            self.group(ident=G2, artist=B),
        ]
        with patch.object(
            n, "request", return_value={"release-groups": rows, "count": 4}
        ) as request:
            meta = self.check("library")
        feed = n.snapshot(server, {"section": "library"})
        self.assertEqual(len(feed["items"]), 1)
        self.assertTrue(meta["complete"])
        self.assertEqual(meta["checkedArtists"], 1)
        query = request.call_args.args[2]["query"]
        self.assertIn("firstreleasedate:[2026-09-26 TO 2026-10-25]", query)
        self.assertIn("arid:" + A, query)

    def test_ambiguous_artist_is_not_included(self):
        self.library()
        with (
            patch.object(n, "request", return_value={"release-groups": [self.group()], "count": 1}),
            patch.object(d, "resolve", return_value=None),
        ):
            meta = self.check("library")
        self.assertEqual(meta["ambiguousArtists"], 1)
        self.assertFalse(meta["complete"])
        self.assertEqual(n.snapshot(server, {"section": "library"})["total"], 0)

    def test_unknown_artist_is_resolved_only_when_a_new_release_matches(self):
        self.library("No New Release")
        self.library()

        def resolve(s, name):
            self.match(name)
            return {"mbid": A, "name": name}

        with (
            patch.object(n, "request", return_value={"release-groups": [self.group()], "count": 1}),
            patch.object(d, "resolve", side_effect=resolve) as resolver,
        ):
            self.check("library")
        resolver.assert_called_once_with(server, "Example Artist")

    def test_all_library_artists_are_checked_beyond_first_forty(self):
        for i in range(63):
            self.library("Artist " + str(i))
        with patch.object(n, "request", return_value={"release-groups": [], "count": 0}) as request:
            meta = self.check("library")
        self.assertEqual(meta["checkedArtists"], 63)
        self.assertEqual(request.call_count, 4)

    def test_semicolon_credits_are_split_but_band_names_are_preserved(self):
        self.library("Earth, Wind & Fire; Example Artist")
        self.assertEqual(n.library_artists(server), ["Earth, Wind & Fire", "Example Artist"])

    def test_country_date_must_belong_to_the_same_release_event(self):
        release = self.edition()
        release["release-events"] = [
            {"date": "2020-01-01", "area": {"iso-3166-1-codes": ["GB"]}},
            {"date": "2026-10-20", "area": {"iso-3166-1-codes": ["US"]}},
        ]
        begin, end = n.window(30)
        self.assertIsNone(n.release_event(release, "GB", False, begin, end))

    def test_worldwide_is_optional_and_local_dates_take_precedence(self):
        release = self.edition()
        release["release-events"] = [
            {"date": "2026-10-15", "area": {"iso-3166-1-codes": ["GB"]}},
            {"date": "2026-10-20", "area": {"iso-3166-1-codes": ["XW"]}},
        ]
        begin, end = n.window(30)
        self.assertEqual(n.release_event(release, "GB", True, begin, end), ("2026-10-15", "GB"))
        self.assertIsNone(n.release_event(self.edition("XW"), "GB", False, begin, end))

    def test_country_feed_works_without_library_and_deduplicates_editions(self):
        with patch.object(
            n,
            "request",
            return_value={
                "releases": [self.edition(), self.edition(day="2026-10-22")],
                "count": 2,
            },
        ):
            meta = self.check()
        feed = n.snapshot(server, {"section": "country"})
        self.assertEqual(feed["libraryArtists"], 0)
        self.assertEqual(feed["total"], 1)
        self.assertEqual(feed["items"][0]["releaseDate"], "2026-10-22")
        self.assertTrue(meta["complete"])

    def test_old_country_editions_are_hidden_unless_requested(self):
        with patch.object(
            n,
            "request",
            return_value={
                "releases": [self.edition(group=self.group("1995-01-01"))],
                "count": 1,
            },
        ):
            self.check()
        self.assertEqual(n.snapshot(server, {"section": "country"})["total"], 0)
        item = n.snapshot(server, {"section": "country", "includeOlder": True})["items"][0]
        self.assertEqual(item["classification"], "catalogue-edition")
        self.assertEqual(item["originalDate"], "1995-01-01")

    def test_future_and_partial_country_dates_are_excluded(self):
        rows = [self.edition(day="2026-10-26"), self.edition(day="2026-10")]
        with patch.object(n, "request", return_value={"releases": rows, "count": 2}):
            self.check()
        self.assertEqual(n.snapshot(server, {"section": "country"})["total"], 0)

    def test_unverified_original_is_labelled_instead_of_claimed_new(self):
        group = self.group()
        group.pop("first-release-date")

        def request(s, entity, params):
            if entity == "release/":
                return {"releases": [self.edition(group=group)], "count": 1}
            raise d.CatalogueUnavailable("musicbrainz.org")

        with patch.object(n, "request", side_effect=request):
            self.check()
        item = n.snapshot(server, {"section": "country"})["items"][0]
        self.assertEqual(item["classification"], "original-date-unconfirmed")

    def test_country_changes_do_not_mix_cached_markets(self):
        with patch.object(n, "request", return_value={"releases": [self.edition()], "count": 1}):
            self.check()
        self.assertEqual(n.snapshot(server, {"section": "country", "country": "LU"})["total"], 0)

    def test_worldwide_toggle_preserves_a_local_edition_of_same_group(self):
        rows = [self.edition(), self.edition("XW", "2026-10-22")]
        with patch.object(n, "request", return_value={"releases": rows, "count": 2}):
            self.check()
        feed = n.snapshot(server, {"section": "country", "worldwide": False})
        self.assertEqual(feed["total"], 1)
        self.assertEqual(feed["items"][0]["eventCountry"], "GB")

    def test_bootlegs_are_excluded(self):
        r = self.edition()
        r["status"] = "Bootleg"
        with patch.object(n, "request", return_value={"releases": [r], "count": 1}):
            self.check()
        self.assertEqual(n.snapshot(server, {"section": "country"})["total"], 0)

    def test_artist_identity_change_hides_old_name_match(self):
        self.library()
        self.match()
        with patch.object(
            n, "request", return_value={"release-groups": [self.group()], "count": 1}
        ):
            self.check("library")
        self.match(ident=B)
        self.assertEqual(n.snapshot(server, {"section": "library"})["total"], 0)

    def test_preferences_are_local_and_do_not_require_online_access(self):
        class H:
            def send_json(self, data):
                self.data = data

        h = H()
        features.store_settings(server, {"discoveryOnline": False})
        with patch.object(d, "urlopen") as request:
            n.post_route(
                h,
                "/api/discovery/releases/preferences",
                {"country": "LU", "days": 7},
                server,
            )
            request.assert_not_called()
        self.assertEqual(n.preferences(server)["country"], "LU")
        with self.assertRaisesRegex(ValueError, "Enable online"):
            n.start(server, {"section": "country"})

    def test_pagination_is_bounded_and_can_continue(self):
        def request(s, entity, params):
            return {"releases": [self.edition() for _ in range(100)], "count": 650}

        meta = {}
        with patch.object(n, "request", side_effect=request) as requester:
            n.country_check(server, self.options, meta)
        self.assertEqual(meta["nextOffset"], 500)
        self.assertTrue(meta["hasMore"])
        self.assertEqual(requester.call_count, 5)
        with patch.object(n, "request", return_value={"releases": [], "count": 650}):
            n.country_check(server, self.options, meta, True)
        self.assertFalse(meta["complete"])
        self.assertTrue(meta["limited"])
        self.assertFalse(meta["hasMore"])

    def test_http_routes_start_country_worker_without_a_library(self):
        import threading
        from urllib.request import Request, urlopen

        host = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=host.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:" + str(host.server_port)

        def post(path, body):
            request = Request(
                base + path,
                data=json.dumps(body).encode(),
                headers={
                    "Content-Type": "application/json",
                    "X-Resonance-Token": server.TOKEN,
                },
                method="POST",
            )
            with urlopen(request, timeout=3) as response:
                return json.load(response)

        try:
            with patch.object(
                n.release_sources,
                "listings",
                return_value=[
                    {
                        "artist": "Example Artist",
                        "album": "New Album",
                        "releaseDate": "2026-10-20",
                        "releaseType": "Album",
                        "genres": ["Jazz"],
                        "source": "Official Charts UK release listings",
                        "url": "https://www.officialcharts.com/new-releases/",
                        "market": "GB",
                        "dateBasis": "release-listing",
                    }
                ],
            ):
                response = post(
                    "/api/discovery/releases/start",
                    {"section": "country", "country": "GB"},
                )
                self.assertTrue(response["running"])
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
            self.assertTrue(feed["check"]["complete"])
            self.assertEqual(feed["libraryArtists"], 0)
        finally:
            host.shutdown()
            host.server_close()

    def test_malformed_pages_do_not_claim_successful_empty_results(self):
        with patch.object(n, "request", return_value={}):
            with self.assertRaisesRegex(ValueError, "release list"):
                self.check("country")
        self.library()
        with patch.object(n, "request", return_value={}):
            with self.assertRaisesRegex(ValueError, "release-group list"):
                self.check("library")

    def test_new_release_cache_uses_one_hour_ttl(self):
        with patch.object(d, "cached_json", return_value={}) as cache:
            n.request(server, "release/", {"query": "country:GB"})
        self.assertEqual(cache.call_args.kwargs["max_age"], 3600)

    def test_genres_are_normalized_from_supported_provider_fields(self):
        import release_genres as g

        labels, broad = g.normalized(
            {
                "genres": [{"name": "Alternative Rock", "count": 2}],
                "primaryGenreName": "Jazz",
                "tags": [
                    {"name": "seen live"},
                    {"name": "trip-hop", "count": 1},
                    {"name": "pop", "count": -1},
                ],
            }
        )
        self.assertEqual(set(labels), {"Alternative Rock", "Jazz", "trip-hop"})
        self.assertEqual(set(broad), {"Alternative & Indie", "Rock", "Jazz", "Electronic & Dance"})
        self.assertEqual(g.extract({"tags": [{"name": "rock", "count": "invalid"}]}), [])

    def test_genre_filter_applies_before_pagination_and_counts_unclassified(self):
        rows = []
        for i in range(55):
            group = self.group(ident=f"{i:08d}-3333-4333-8333-333333333333")
            group["title"] = f"Album {i:03d}"
            if i == 0:
                group["genres"] = [{"name": "jazz"}]
            elif i > 1:
                group["tags"] = [{"name": "alternative rock"}]
            rows.append(self.edition(group=group))
        with patch.object(n, "request", return_value={"releases": rows, "count": 55}):
            self.check()
        with patch.object(n, "request") as request:
            jazz = n.snapshot(server, {"section": "country", "genre": "Jazz", "limit": 1})
            unknown = n.snapshot(server, {"section": "country", "genre": "unclassified"})
            rock = n.snapshot(
                server,
                {"section": "country", "genre": "Rock", "offset": 48, "limit": 48},
            )
            request.assert_not_called()
        self.assertEqual(jazz["total"], 1)
        self.assertEqual(jazz["items"][0]["album"], "Album 000")
        self.assertEqual(jazz["genreCounts"]["Rock"], 53)
        self.assertEqual(jazz["unfilteredTotal"], 55)
        self.assertEqual(unknown["total"], 1)
        self.assertEqual(unknown["items"][0]["album"], "Album 001")
        self.assertEqual(rock["total"], 53)
        self.assertEqual(len(rock["items"]), 5)

    def test_library_genres_and_local_preference_survive_restart_read(self):
        self.library()
        self.match()
        group = self.group()
        group["genres"] = [{"name": "deep house"}]
        with patch.object(n, "request", return_value={"release-groups": [group], "count": 1}):
            self.check("library")

        class H:
            def send_json(self, data):
                self.data = data

        with patch.object(n, "request") as request:
            n.post_route(
                H(),
                "/api/discovery/releases/preferences",
                {"genre": "Electronic & Dance"},
                server,
            )
            request.assert_not_called()
        self.assertEqual(n.preferences(server)["genre"], "Electronic & Dance")
        self.assertEqual(d.snapshot(server)["releasePreferences"]["genre"], "Electronic & Dance")
        self.assertEqual(n.snapshot(server, {"section": "library"})["total"], 1)
        self.assertEqual(n.snapshot(server, {"section": "library", "genre": "Jazz"})["total"], 0)
        with self.assertRaises(ValueError):
            n.filters(server, {"genre": "arbitrary"})
        self.assertEqual(
            n.feed_key("library", self.options),
            n.feed_key("library", {**self.options, "genre": "Jazz"}),
        )

    def test_cached_genres_are_kept_when_next_response_has_none(self):
        group = self.group()
        group["tags"] = [{"name": "jazz"}]
        with patch.object(
            n,
            "request",
            return_value={"releases": [self.edition(group=group)], "count": 1},
        ):
            self.check()
        with patch.object(n, "request", return_value={"releases": [self.edition()], "count": 1}):
            self.check()
        self.assertEqual(n.snapshot(server, {"section": "country", "genre": "Jazz"})["total"], 1)


if __name__ == "__main__":
    unittest.main()
