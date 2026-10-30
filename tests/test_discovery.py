import json, tempfile, unittest, io, time
from urllib.error import HTTPError
from email.message import Message
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server, features, discovery

A = "11111111-1111-4111-8111-111111111111"
B = "22222222-2222-4222-8222-222222222222"
R = "33333333-3333-4333-8333-333333333333"


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = server.DATA
        server.DATA = Path(self.tmp.name) / "data"
        server.init()
        discovery.init(server)
        with server.db() as c:
            c.execute(
                "INSERT INTO tracks VALUES (?,?,?,?,?,?,?,?)",
                (
                    "test.flac",
                    "library",
                    "Example Artist",
                    "Example Album",
                    "Track",
                    240,
                    "flac",
                    100,
                ),
            )
        discovery.job.update(
            running=False,
            cancel=False,
            candidates=[],
            errors=[],
            warnings=[],
            retryAt=0,
        )
        discovery.service_cooldowns.clear()
        discovery.last_fetch.clear()

    def tearDown(self):
        server.DATA = self.old
        server.diag.close()
        self.tmp.cleanup()

    def test_no_request_before_consent(self):
        with patch.object(discovery, "urlopen") as request:
            with self.assertRaises(ValueError):
                discovery.cached_json(server, discovery.MB + "artist?query=example")
            with self.assertRaises(ValueError):
                discovery.start(server, {})
            request.assert_not_called()

    def test_profile_uses_tagged_artists(self):
        p = discovery.profile(server)
        self.assertEqual(p[0]["artist"], "Example Artist")
        self.assertEqual(p[0]["albums"], ["Example Album"])

    def test_owned_album_is_index_presence_not_full_release_claim(self):
        self.assertEqual(
            discovery.ownership(server, "example artist", "Example Album"),
            "album-in-library",
        )
        self.assertEqual(
            discovery.ownership(server, "Other Artist", "Example Album"),
            "not-in-library",
        )

    def test_ambiguous_artist_is_not_guessed(self):
        choices = [
            {"id": A, "name": "Example Artist", "disambiguation": "first"},
            {"id": B, "name": "Example Artist", "disambiguation": "second"},
        ]
        with patch.object(discovery, "mb", return_value={"artists": choices}):
            result = discovery.resolve(server, "Example Artist")
        self.assertIsNone(result)
        self.assertEqual(len(discovery.job["candidates"][0]["choices"]), 2)

    def test_similar_response_unpacks_and_removes_seed(self):
        response = {
            A: [{"similar_artist_mbid": A, "similar_artist_name": "Seed"}],
            B: [{"similar_artist_mbid": B, "similar_artist_name": "Related"}],
        }
        with patch.object(discovery, "cached_json", return_value=response):
            result = discovery.similar_artists(server, A, "easy")
        self.assertEqual(result, [{"mbid": B, "name": "Related"}])

    def test_reasons_merge_and_saved_status_persists(self):
        item = {
            "kind": "artist",
            "mbid": B,
            "artist": "Related",
            "source": "Test",
            "reason": "First reason",
        }
        discovery.add(server, dict(item))
        discovery.add(server, {**item, "reason": "Second reason"})
        iid = "artist:" + B
        with server.db() as c:
            c.execute("INSERT INTO discovery_feedback VALUES (?,?)", (iid, "saved"))
        snap = discovery.snapshot(server)
        self.assertEqual(len(snap["items"]), 1)
        self.assertEqual(snap["items"][0]["feedback"], "saved")
        self.assertEqual(len(snap["items"][0]["reasons"]), 2)

    def test_cache_can_be_read_offline_without_network(self):
        url = discovery.MB + "artist?query=example"
        import time

        with server.db() as c:
            c.execute(
                "INSERT INTO discovery_cache VALUES (?,?,?)",
                (url, json.dumps({"artists": []}), time.time()),
            )
        with patch.object(discovery, "urlopen") as request:
            self.assertEqual(discovery.cached_json(server, url), {"artists": []})
            request.assert_not_called()

    def test_worker_mocked_end_to_end_no_real_external_requests(self):
        features.store_settings(server, {"discoveryOnline": True})

        def metadata(s, entity, params):
            if entity == "artist/":
                return {"artists": [{"id": A, "name": "Example Artist"}]}
            if entity == "release-group":
                return {
                    "release-groups": [
                        {
                            "id": R,
                            "title": "A Missing Album",
                            "primary-type": "Album",
                            "secondary-types": [],
                            "first-release-date": "2000",
                        }
                    ]
                }
            return {}

        with (
            patch.object(discovery, "mb", side_effect=metadata),
            patch.object(
                discovery,
                "similar_artists",
                return_value=[{"mbid": B, "name": "A Related Artist"}],
            ),
            patch.object(discovery, "urlopen") as request,
        ):
            discovery.worker(server, ["Example Artist"], "easy", "")
            request.assert_not_called()
        items = discovery.snapshot(server)["items"]
        self.assertTrue(any(i["kind"] == "artist" for i in items))
        self.assertTrue(any(i["kind"] == "missing-album" for i in items))
        self.assertFalse(discovery.job["running"])

    def test_cannot_start_from_non_library_seed(self):
        features.store_settings(server, {"discoveryOnline": True})
        with self.assertRaises(ValueError):
            discovery.start(server, {"artist": "Not In Library"})


class DiscoveryOutageTests(unittest.TestCase):
    setUp = DiscoveryTests.setUp
    tearDown = DiscoveryTests.tearDown

    # Use the same isolated library/settings fixture, without inheriting the base test methods twice.
    def enable(self):
        features.store_settings(server, {"discoveryOnline": True})

    def unavailable(self, code=503, after=None):
        headers = Message()
        if after is not None:
            headers["Retry-After"] = str(after)
        return HTTPError(discovery.MB + "artist/", code, "busy", headers, io.BytesIO(b""))

    def test_transient_503_retries_and_saves_success(self):
        self.enable()
        url = discovery.MB + "artist?query=retry"
        with (
            patch.object(
                discovery,
                "urlopen",
                side_effect=[
                    self.unavailable(),
                    self.unavailable(),
                    io.BytesIO(b'{"artists":[]}'),
                ],
            ) as request,
            patch.object(discovery, "wait_for_retry"),
        ):
            result = discovery.cached_json(server, url)
        self.assertEqual(result, {"artists": []})
        self.assertEqual(request.call_count, 3)
        with server.db() as c:
            self.assertIsNotNone(
                c.execute("SELECT value FROM discovery_cache WHERE key=?", (url,)).fetchone()
            )
        self.assertEqual(discovery.job["errors"], [])

    def test_exhausted_retries_use_stale_cache_and_warn(self):
        self.enable()
        url = discovery.MB + "artist?query=stale"
        old = {"artists": [{"id": A, "name": "Example Artist"}]}
        with server.db() as c:
            c.execute(
                "INSERT INTO discovery_cache VALUES (?,?,?)",
                (url, json.dumps(old), time.time() - 8 * 86400),
            )
        with (
            patch.object(
                discovery, "urlopen", side_effect=lambda *a, **k: self.unavailable()
            ) as request,
            patch.object(discovery, "wait_for_retry"),
        ):
            self.assertEqual(discovery.cached_json(server, url), old)
        self.assertEqual(request.call_count, 3)
        self.assertTrue(discovery.job["warnings"])
        self.assertGreater(discovery.job["retryAt"], time.time())

    def test_cooldown_prevents_hammering_other_requests(self):
        self.enable()
        with (
            patch.object(
                discovery, "urlopen", side_effect=lambda *a, **k: self.unavailable()
            ) as request,
            patch.object(discovery, "wait_for_retry"),
        ):
            for query in ("one", "two"):
                with self.assertRaises(discovery.CatalogueUnavailable):
                    discovery.cached_json(server, discovery.MB + "artist?query=" + query)
        self.assertEqual(request.call_count, 3)

    def test_retry_after_is_honoured_without_long_blocking_wait(self):
        self.enable()
        before = time.time()
        with (
            patch.object(discovery, "urlopen", side_effect=self.unavailable(after=120)) as request,
            patch.object(discovery, "wait_for_retry"),
        ):
            with self.assertRaises(discovery.CatalogueUnavailable):
                discovery.cached_json(server, discovery.MB + "artist?query=long")
        self.assertEqual(request.call_count, 1)
        self.assertGreaterEqual(discovery.service_cooldowns["musicbrainz.org"], before + 120)

    def test_stop_during_retry_prevents_the_next_external_request(self):
        self.enable()

        def stop(*a):
            discovery.job["cancel"] = True

        with (
            patch.object(discovery, "urlopen", side_effect=self.unavailable()) as request,
            patch.object(discovery, "wait_for_retry", side_effect=stop),
        ):
            with self.assertRaisesRegex(ValueError, "stopped"):
                discovery.cached_json(server, discovery.MB + "artist?query=stop")
        self.assertEqual(request.call_count, 1)

    def test_permanent_http_errors_are_not_retried(self):
        self.enable()
        with patch.object(discovery, "urlopen", side_effect=self.unavailable(code=404)) as request:
            with self.assertRaisesRegex(ValueError, "404"):
                discovery.cached_json(server, discovery.MB + "artist?query=missing")
        self.assertEqual(request.call_count, 1)

    def test_stale_cache_is_available_offline_without_consent(self):
        url = discovery.MB + "artist?query=offline"
        with server.db() as c:
            c.execute(
                "INSERT INTO discovery_cache VALUES (?,?,?)",
                (url, '{"artists":[]}', time.time() - 8 * 86400),
            )
        with patch.object(discovery, "urlopen") as request:
            self.assertEqual(discovery.cached_json(server, url), {"artists": []})
            request.assert_not_called()

    def test_musicbrainz_album_outage_does_not_block_listenbrainz_artists(self):
        self.enable()
        with (
            patch.object(discovery, "resolve", return_value={"mbid": A, "name": "Example Artist"}),
            patch.object(
                discovery,
                "album_items",
                side_effect=discovery.CatalogueUnavailable("musicbrainz.org"),
            ),
            patch.object(
                discovery,
                "similar_artists",
                return_value=[{"mbid": B, "name": "Related Artist"}],
            ),
        ):
            discovery.worker(server, ["Example Artist"], "easy", "")
        snap = discovery.snapshot(server)
        self.assertTrue(any(i["artist"] == "Related Artist" for i in snap["items"]))
        self.assertTrue(snap["job"]["errors"])
        self.assertNotEqual(snap["job"]["progress"], "Recommendations ready")

    def test_retry_after_date_and_invalid_values(self):
        from email.utils import formatdate

        self.assertGreater(
            discovery.retry_delay(formatdate(time.time() + 120, usegmt=True), 2), 100
        )
        self.assertEqual(discovery.retry_delay("garbage", 2), 2)
        self.assertEqual(discovery.retry_delay("inf", 2), 2)


if __name__ == "__main__":
    unittest.main()
