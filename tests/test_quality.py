"""Regression outcomes from the quality review; no live credentials or peer activity."""

import concurrent.futures, json, tempfile, threading, time, unittest, uuid, sqlite3
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server, downloads, album_jobs, library_sync, library_index, features, identity, storage, new_releases, discovery, config_journal


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = server.DATA
        server.DATA = Path(self.tmp.name) / "data"
        server.init()
        self.file = {
            "username": "fixture-peer",
            "filename": "Music/Artist/Album/01.flac",
            "size": 10,
        }

    def tearDown(self):
        server.DATA = self.old
        self.tmp.cleanup()

    def accepted(self, path, method="GET", body=None):
        return {"batch": {"id": body["id"]}, "failures": []}

    def test_timeout_keeps_intent_and_double_click_does_not_repeat(self):
        with patch.object(server, "slsk", side_effect=TimeoutError):
            first = server.queue_file(self.file, "query")
            second = server.queue_file(self.file, "query")
        self.assertEqual(first["status"], "Unconfirmed")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(album_jobs.request_index(server)), 1)

    def test_simultaneous_queue_calls_have_one_upstream_operation(self):
        calls = []

        def network(*args):
            calls.append(args)
            time.sleep(0.05)
            return self.accepted(*args)

        with (
            patch.object(server, "slsk", side_effect=network),
            concurrent.futures.ThreadPoolExecutor(2) as pool,
        ):
            results = list(pool.map(lambda _: server.queue_file(self.file, "query"), range(2)))
        self.assertEqual(len(calls), 1)
        self.assertEqual(results[0]["id"], results[1]["id"])

    def test_after_acceptance_lost_reply_reconciles_without_resubmission(self):
        with patch.object(server, "slsk", side_effect=TimeoutError):
            record = server.queue_file(self.file, "query")
        with patch.object(
            server,
            "slsk",
            return_value={
                "transfers": [
                    {
                        "filename": self.file["filename"],
                        "id": "transfer",
                        "state": "InProgress, Transferring",
                    }
                ]
            },
        ) as network:
            restored = downloads.retry(server, record["id"])
        self.assertEqual(network.call_count, 1)
        self.assertEqual(restored["transferId"], "transfer")

    def test_confirmed_absence_retries_the_same_operation_id(self):
        with patch.object(server, "slsk", side_effect=TimeoutError):
            record = server.queue_file(self.file, "query")
        calls = []

        def network(path, method="GET", body=None):
            calls.append((path, method, body))
            if method == "GET":
                raise server.UpstreamError("not found", status=404)
            return self.accepted(path, method, body)

        with patch.object(server, "slsk", side_effect=network):
            restored = downloads.retry(server, record["id"])
        self.assertEqual(restored["status"], "Queued")
        self.assertEqual(calls[-1][2]["id"], record["batchId"])

    def test_album_missing_batches_resume_and_preserve_destination(self):
        body = {
            "id": str(uuid.uuid4()),
            "username": self.file["username"],
            "directory": "Music/Artist/Album",
            "files": [
                self.file,
                {**self.file, "filename": "Music/Artist/Album/Artwork/cover.jpg"},
            ],
        }
        with patch.object(server, "slsk", side_effect=TimeoutError):
            job = album_jobs.enqueue(server, body)

        def network(path, method="GET", body=None):
            if method == "GET":
                raise server.UpstreamError("not found", status=404)
            return self.accepted(path, method, body)

        with patch.object(server, "slsk", side_effect=network) as upstream:
            restored = album_jobs.retry(server, job["id"])
        self.assertTrue(all(f["status"] == "Queued" for f in restored["files"]))
        self.assertEqual(
            [x["requestId"] for x in job["files"]],
            [x["requestId"] for x in restored["files"]],
        )
        self.assertEqual(
            [
                call.args[2]["options"]["destination"]
                for call in upstream.call_args_list
                if len(call.args) == 3
            ],
            ["Album", "Album/Artwork"],
        )

    def test_replacement_updates_destination_file_and_album_total(self):
        body = {
            "id": str(uuid.uuid4()),
            "username": self.file["username"],
            "directory": "Music/Artist/Album",
            "files": [self.file],
        }
        with patch.object(server, "slsk", side_effect=self.accepted):
            job = album_jobs.enqueue(server, body)
        record = album_jobs.request_index(server)[job["files"][0]["requestId"]]
        record["status"] = "Rejected"
        server.save_request(record)
        replacement = {
            **self.file,
            "username": "another-peer",
            "filename": "Different/Folder/01.flac",
            "size": 20,
        }
        with patch.object(server, "slsk", side_effect=self.accepted) as upstream:
            new = server.queue_file(replacement, "query", record["id"])
        self.assertEqual(upstream.call_args.args[2]["options"]["destination"], "Album")
        current = album_jobs.list_jobs(server)[0]
        self.assertEqual(current["size"], 20)
        self.assertEqual(current["files"][0]["file"]["username"], "another-peer")
        self.assertEqual(new["attempts"], [self.file])

    def test_completed_with_errors_is_not_successful(self):
        from transfer_state import classify, succeeded

        self.assertFalse(succeeded("Completed, Errored"))
        self.assertEqual(classify("Completed, Cancelled"), "cancelled")
        self.assertTrue(succeeded("Completed, Succeeded"))

    def test_ready_warning_is_allowed_but_faulted_is_not(self):
        with patch.object(
            server,
            "slsk",
            return_value={
                "shares": {
                    "ready": True,
                    "scanning": False,
                    "scanPending": True,
                    "errors": 1,
                }
            },
        ):
            library_sync.wait_ready(server, False)
        self.assertIn("retained", server.scan_state["warning"])
        with patch.object(
            server,
            "slsk",
            return_value={
                "shares": {
                    "ready": True,
                    "scanning": False,
                    "faulted": True,
                    "errors": 1,
                }
            },
        ):
            with self.assertRaises(ValueError):
                library_sync.wait_ready(server, False)

    def test_failed_tag_read_preserves_last_good_metadata_and_retries_later(self):
        root = Path(self.tmp.name) / "music"
        root.mkdir()
        path = root / "01.flac"
        path.write_bytes(b"invalid")
        with server.db() as c:
            c.execute(
                "INSERT INTO tracks VALUES (?,?,?,?,?,?,?,?)",
                (
                    str(path),
                    str(root),
                    "Known Artist",
                    "Known Album",
                    "Known Title",
                    123,
                    "flac",
                    7,
                ),
            )
        with (
            patch.object(library_sync, "wait_ready"),
            patch.object(library_sync, "metadata_inventory", return_value=None),
            patch.object(
                library_sync,
                "local_inventory",
                return_value=({str(path): (path, root, {"size": 7})}, 1),
            ),
            patch("mutagen.File", side_effect=OSError("temporary")) as read,
        ):
            server.scan_lock.acquire()
            library_sync.import_cache(server)
            server.scan_lock.acquire()
            library_sync.import_cache(server)
        self.assertEqual(read.call_count, 2)
        with server.db() as c:
            row = c.execute("SELECT * FROM tracks").fetchone()
            self.assertEqual(row["artist"], "Known Artist")
            self.assertEqual(row["duration"], 123)

    def test_failed_folder_enumeration_keeps_previous_snapshot(self):
        root = Path(self.tmp.name) / "music"
        root.mkdir()
        with server.db() as c:
            c.execute(
                "INSERT INTO tracks VALUES (?,?,?,?,?,?,?,?)",
                ("old", "old", "Artist", "Album", "Title", 1, "flac", 1),
            )
        server.scan_lock.acquire()
        server.scan([str(root), str(root / "unavailable")])
        with server.db() as c:
            self.assertEqual(c.execute("SELECT path FROM tracks").fetchone()[0], "old")

    def test_removed_root_does_not_leave_stale_tracks(self):
        root = Path(self.tmp.name) / "music"
        root.mkdir()
        with server.db() as c:
            c.execute(
                "INSERT INTO tracks VALUES (?,?,?,?,?,?,?,?)",
                ("old", "removed", "Artist", "Album", "Title", 1, "flac", 1),
            )
        server.scan_lock.acquire()
        server.scan([str(root)])
        with server.db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM tracks").fetchone()[0], 0)

    def test_listing_refresh_keeps_review_scores_artwork_and_feedback(self):
        item = {
            "id": "release",
            "kind": new_releases.KINDS["country"],
            "artist": "Artist",
            "album": "Album",
            "eventCountry": "GB",
            "releaseDate": "2026-10-30",
            "reason": "Original",
            "ratings": [
                {
                    "publisher": "Fixture",
                    "url": "https://example.org/review",
                    "value": 4,
                    "best": 5,
                }
            ],
            "artwork": "https://is1-ssl.mzstatic.com/cover.jpg",
            "coveragePreview": {"text": "A preview"},
        }
        new_releases.store(server, item.copy())
        with server.db() as c:
            c.execute("INSERT INTO discovery_feedback VALUES (?,?)", ("release", "saved"))
        new_releases.store(
            server,
            {
                **item,
                "ratings": [],
                "artwork": "",
                "coveragePreview": None,
                "reason": "Refreshed",
            },
        )
        with server.db() as c:
            updated = json.loads(
                c.execute("SELECT value FROM discovery_items WHERE id=?", ("release",)).fetchone()[
                    0
                ]
            )
            self.assertEqual(updated["ratings"][0]["value"], 4)
            self.assertTrue(updated["coveragePreview"])
            self.assertEqual(
                c.execute("SELECT status FROM discovery_feedback").fetchone()[0],
                "saved",
            )

    def test_unicode_and_editions_are_distinct_and_old_feedback_migrates(self):
        self.assertNotEqual(
            identity.release_key("艺人甲", "专辑"),
            identity.release_key("艺人乙", "专辑"),
        )
        self.assertNotEqual(
            identity.release_key("Café", "Album"), identity.release_key("Cafe", "Album")
        )
        self.assertNotEqual(
            identity.release_key("Artist", "Album"),
            identity.release_key("Artist", "Album (Deluxe)"),
        )
        old = "new-country-release:external:GB:old"
        item = {
            "id": old,
            "kind": new_releases.KINDS["country"],
            "country": "GB",
            "artist": "Artist",
            "album": "Album (Deluxe)",
            "ratings": [{"value": 4}],
        }
        with server.db() as c:
            c.execute("INSERT INTO discovery_items VALUES (?,?)", (old, json.dumps(item)))
            c.execute("INSERT INTO discovery_feedback VALUES (?,?)", (old, "saved"))
        identity.migrate(server)
        new = identity.resolve(server, old)
        with server.db() as c:
            self.assertEqual(
                c.execute("SELECT status FROM discovery_feedback WHERE id=?", (new,)).fetchone()[0],
                "saved",
            )
            self.assertIn(
                "ratings",
                json.loads(
                    c.execute("SELECT value FROM discovery_items WHERE id=?", (new,)).fetchone()[0]
                ),
            )

    def test_library_index_is_reused_and_invalidated_by_database_revision(self):
        first = library_index.get(server)
        self.assertIs(first, library_index.get(server))
        with server.db() as c:
            c.execute(
                "INSERT INTO tracks VALUES (?,?,?,?,?,?,?,?)",
                ("a", "root", "Artist", "Album", "Title", 1, "flac", 1),
            )
        second = library_index.get(server)
        self.assertIsNot(first, second)
        self.assertEqual(discovery.ownership(server, "Artist", "Album"), "album-in-library")

    def test_connections_close_and_settings_updates_are_atomic(self):
        with server.db() as connection:
            connection.execute("SELECT 1")
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            list(
                pool.map(
                    lambda pair: features.store_settings(server, dict([pair])),
                    [("releaseDays", 90), ("discoveryOnline", True)],
                )
            )
        self.assertEqual(server.settings(True)["releaseDays"], 90)
        self.assertTrue(server.settings(True)["discoveryOnline"])

    def test_configuration_rollback_and_comment_preservation(self):
        path = Path(self.tmp.name) / "engine.yml"
        original = b"# Keep this comment\nshares:\n  directories: []\n"
        path.write_bytes(original)
        with patch.object(storage, "settings_patch", side_effect=OSError("database unavailable")):
            with self.assertRaises(OSError):
                config_journal.commit(
                    server,
                    path,
                    "shares:\n  directories: [new]\n",
                    {"sharingPaused": True},
                )
        self.assertEqual(path.read_bytes(), original)
        y = features.yaml_module()
        self.assertIn("# Keep this comment", y.safe_dump(y.safe_load(original.decode())))

    def test_post_commit_error_restores_both_stores(self):
        path = Path(self.tmp.name) / "engine.yml"
        path.write_text("shares: old\n")
        storage.settings_patch(server, {"sharingPaused": False})
        original_patch = storage.settings_patch
        calls = []

        def patch_then_fail(app, values):
            calls.append(values)
            original_patch(app, values)
            if len(calls) == 1:
                raise OSError("post-commit failure")

        with patch.object(storage, "settings_patch", side_effect=patch_then_fail):
            with self.assertRaises(OSError):
                config_journal.commit(server, path, "shares: new\n", {"sharingPaused": True})
        self.assertEqual(path.read_text(), "shares: old\n")
        self.assertFalse(server.settings(True)["sharingPaused"])

    def test_aliases_and_exclusions_round_trip(self):
        root = Path(self.tmp.name)
        self.assertEqual(
            features.share_path("[Collection]" + str(root)), "[Collection]" + str(root)
        )
        self.assertEqual(features.share_path("!" + str(root)), "!" + str(root))


if __name__ == "__main__":
    unittest.main()
