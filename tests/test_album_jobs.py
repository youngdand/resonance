import json, tempfile, unittest, uuid
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server, album_jobs


class AlbumJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = server.DATA
        server.DATA = Path(self.tmp.name)
        server.init()
        self.files = [
            {"username": "person", "filename": r"Music\Album\01.flac", "size": 10},
            {"username": "person", "filename": r"Music\Album\02.flac", "size": 20},
            {
                "username": "person",
                "filename": r"Music\Album\Artwork\cover.jpg",
                "size": 2,
            },
        ]
        self.body = {
            "id": str(uuid.uuid4()),
            "username": "person",
            "directory": "Music/Album",
            "query": "artist album",
            "files": self.files,
        }

    def tearDown(self):
        server.DATA = self.old
        server.diag.close()
        self.tmp.cleanup()

    def enqueue(self, *args, **kwargs):
        return {"batch": {"id": args[2]["id"]}, "failures": []}

    def test_batches_group_files_by_destination_and_keep_nested_artwork(self):
        with patch.object(server, "slsk", side_effect=self.enqueue) as upstream:
            job = album_jobs.enqueue(server, self.body)
        self.assertEqual(upstream.call_count, 2)
        self.assertEqual([len(c.args[2]["files"]) for c in upstream.call_args_list], [2, 1])
        self.assertEqual(
            upstream.call_args_list[-1].args[2]["options"]["destination"],
            "Album/Artwork",
        )
        self.assertEqual(job["expected"], 3)
        self.assertEqual(job["completed"], 0)

    def test_browser_retry_is_idempotent(self):
        with patch.object(server, "slsk", side_effect=self.enqueue) as upstream:
            one = album_jobs.enqueue(server, self.body)
            two = album_jobs.enqueue(server, self.body)
        self.assertEqual(upstream.call_count, 2)
        self.assertEqual(one["id"], two["id"])

    def test_partial_failure_and_missing_transfer_cannot_complete_album(self):
        def remote(path, method, body):
            return {
                "batch": {"id": body["id"]},
                "failures": [{"filename": body["files"][-1]["filename"]}],
            }

        with patch.object(server, "slsk", side_effect=remote):
            job = album_jobs.enqueue(server, self.body)
        self.assertEqual(job["failed"], 2)
        self.assertEqual(job["status"], "Needs attention")
        with patch.object(server, "slsk", return_value=[]):
            server.sync_downloads()
        self.assertNotEqual(album_jobs.list_jobs(server)[0]["status"], "Selected files complete")

    def test_intent_survives_unconfirmed_post_and_retry_does_not_repeat_it(self):
        with patch.object(server, "slsk", side_effect=TimeoutError("unconfirmed")) as upstream:
            album_jobs.enqueue(server, self.body)
            job = album_jobs.enqueue(server, self.body)
        self.assertEqual(upstream.call_count, 4)
        self.assertEqual(job["failed"], 3)
        self.assertEqual(len(album_jobs.request_index(server)), 3)

    def test_replacement_stays_attached_to_expected_file(self):
        with patch.object(server, "slsk", side_effect=self.enqueue):
            job = album_jobs.enqueue(server, self.body)
        item = job["files"][0]
        request = album_jobs.request_index(server)[item["requestId"]]
        request["status"] = "Rejected"
        server.save_request(request)
        with patch.object(server, "slsk", return_value={"enqueued": [{}]}):
            replacement = server.queue_file(
                {**self.files[0], "username": "other"}, "q", request["id"]
            )
        updated = album_jobs.list_jobs(server)[0]
        self.assertEqual(updated["files"][0]["requestId"], replacement["id"])
        self.assertEqual(updated["expected"], 3)

    def test_completion_requires_every_expected_file_including_artwork(self):
        with patch.object(server, "slsk", side_effect=self.enqueue):
            album_jobs.enqueue(server, self.body)
        requests = list(album_jobs.request_index(server).values())
        for r in requests[:2]:
            r["status"] = "Completed, Succeeded"
            server.save_request(r)
        self.assertEqual(album_jobs.list_jobs(server)[0]["completed"], 2)
        self.assertNotEqual(album_jobs.list_jobs(server)[0]["status"], "Selected files complete")
        requests[2]["status"] = "Completed, Succeeded"
        server.save_request(requests[2])
        self.assertEqual(album_jobs.list_jobs(server)[0]["status"], "Selected files complete")

    def test_outside_and_traversal_paths_have_no_side_effect(self):
        for path in (r"Music\Other\01.flac", r"Music\Album\..\evil.flac"):
            with patch.object(server, "slsk") as upstream:
                with self.assertRaises(ValueError):
                    album_jobs.enqueue(
                        server,
                        {**self.body, "files": [{**self.files[0], "filename": path}]},
                    )
                upstream.assert_not_called()

    def test_same_id_cannot_be_reused_for_another_selection(self):
        with patch.object(server, "slsk", side_effect=self.enqueue):
            album_jobs.enqueue(server, self.body)
        with self.assertRaises(ValueError):
            album_jobs.enqueue(server, {**self.body, "files": self.files[:1]})


if __name__ == "__main__":
    unittest.main()
