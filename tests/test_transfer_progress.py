import io, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server, transfer_progress, realtime


class TransferProgressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = server.DATA
        server.DATA = Path(self.tmp.name)
        server.init()
        transfer_progress.caches.clear()
        transfer_progress.samples.clear()
        transfer_progress.failures.clear()
        self.file = {
            "id": "remote",
            "filename": r"Music\Album\song.flac",
            "state": "InProgress, Transferring",
            "size": 1000,
            "bytesTransferred": 250,
            "averageSpeed": 100,
        }
        self.remote = [{"username": "peer", "directories": [{"files": [self.file]}]}]
        server.save_request(
            {
                "id": "request",
                "file": {
                    "username": "peer",
                    "filename": self.file["filename"],
                    "size": 1000,
                },
                "status": "Queued",
                "created": 1,
            }
        )

    def tearDown(self):
        server.DATA = self.old
        server.diag.close()
        self.tmp.cleanup()

    def test_download_snapshot_has_progress_and_speed_and_shares_one_upstream_read(
        self,
    ):
        with patch.object(server, "slsk", return_value=self.remote) as upstream:
            one = transfer_progress.snapshot(server, "downloads")
            two = transfer_progress.snapshot(server, "downloads")
        self.assertIs(one, two)
        self.assertEqual(upstream.call_count, 1)
        self.assertEqual(one["requests"][0]["bytesTransferred"], 250)
        self.assertEqual(one["requests"][0]["currentSpeed"], 100)

    def test_uploads_include_all_transfer_rows(self):
        with patch.object(server, "slsk", return_value=self.remote):
            data = transfer_progress.snapshot(server, "uploads")
        self.assertEqual(data["uploads"][0]["username"], "peer")
        self.assertEqual(data["uploads"][0]["bytesTransferred"], 250)

    def test_speed_uses_deltas_and_shows_a_stall_as_zero(self):
        def row(count, state="InProgress, Transferring"):
            return {**self.file, "bytesTransferred": count, "state": state}

        self.assertEqual(
            transfer_progress.add_speeds("uploads", [row(250)], 1)[0]["currentSpeed"],
            100,
        )
        self.assertEqual(
            transfer_progress.add_speeds("uploads", [row(550)], 2)[0]["currentSpeed"],
            300,
        )
        self.assertEqual(
            transfer_progress.add_speeds("uploads", [row(550)], 3)[0]["currentSpeed"], 0
        )
        self.assertEqual(
            transfer_progress.add_speeds("uploads", [row(1000, "Completed, Succeeded")], 4)[0][
                "currentSpeed"
            ],
            0,
        )

    def test_failed_snapshot_does_not_erase_requests_and_backs_off(self):
        with patch.object(
            server, "slsk", side_effect=ValueError("temporarily offline")
        ) as upstream:
            for _ in range(2):
                with self.assertRaises(ValueError):
                    transfer_progress.snapshot(server, "downloads")
        self.assertEqual(upstream.call_count, 1)
        with server.db() as c:
            r = json.loads(c.execute("SELECT value FROM requests").fetchone()[0])
        self.assertEqual(r["status"], "Queued")

    def test_replaced_cancelled_and_archived_state_is_preserved(self):
        r = {
            "id": "request",
            "file": {
                "username": "peer",
                "filename": self.file["filename"],
                "size": 1000,
            },
            "status": "Cancelled",
            "archived": True,
        }
        server.save_request(r)
        with patch.object(server, "slsk", return_value=self.remote):
            data = transfer_progress.snapshot(server, "downloads")
        self.assertEqual(data["requests"][0]["status"], "Cancelled")
        self.assertTrue(data["requests"][0]["archived"])

    def test_invalid_upstream_list_does_not_publish_empty_success(self):
        with patch.object(server, "slsk", return_value={}):
            with self.assertRaisesRegex(ValueError, "invalid transfer list"):
                transfer_progress.snapshot(server, "uploads")
        self.assertNotIn("uploads", transfer_progress.caches)

    def test_sse_transfers_are_scoped_to_the_open_page(self):
        class Output(io.BytesIO):
            count = 0

            def flush(self):
                self.count += 1
                if self.count >= 2:
                    raise BrokenPipeError()

        class Handler:
            wfile = Output()

            def send_response(self, *args):
                pass

            def send_header(self, *args):
                pass

            def end_headers(self):
                pass

        h = Handler()
        with (
            patch.object(realtime, "start"),
            patch.object(realtime.condition, "wait"),
            patch.object(
                transfer_progress,
                "snapshot",
                return_value={"direction": "uploads", "uploads": [], "sampledAt": 1},
            ) as snapshot,
        ):
            realtime.stream(h, server, "uploads")
        snapshot.assert_called_once_with(server, "uploads")
        self.assertIn(b"event: transfers", h.wfile.getvalue())

    def test_invalid_direction_is_rejected(self):
        with self.assertRaises(ValueError):
            transfer_progress.snapshot(server, "invalid")


if __name__ == "__main__":
    unittest.main()
