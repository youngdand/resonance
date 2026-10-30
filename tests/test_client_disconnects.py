"""Browser stream disconnects must end quietly, without a second HTTP response."""

import io
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import realtime, server
from http.server import BaseHTTPRequestHandler


class ClientDisconnectTests(unittest.TestCase):
    def handler(self, fail):
        class Output(io.BytesIO):
            failed = False

            def write(self, data):
                if fail in data:
                    self.failed = True
                    raise ConnectionAbortedError(10053, "Connection aborted by host software")
                if self.failed:
                    raise AssertionError("Tried writing after disconnect")
                return super().write(data)

        return SimpleNamespace(
            wfile=Output(), send_response=Mock(), send_header=Mock(), end_headers=Mock()
        )

    def stream(self, h, direction="downloads", snapshot=None):
        with (
            patch.object(realtime, "start"),
            patch.object(realtime.condition, "wait"),
            patch.object(
                realtime.transfer_progress,
                "snapshot",
                return_value=snapshot or {"direction": direction},
            ) as snap,
        ):
            realtime.stream(h, server, direction)
        return snap

    def test_initial_write_abort_is_quiet(self):
        h = self.handler(b": connected")
        snap = self.stream(h)
        self.assertTrue(h.wfile.failed)
        snap.assert_not_called()

    def test_heartbeat_abort_is_quiet(self):
        h = self.handler(b": heartbeat")
        self.stream(h)
        self.assertTrue(h.wfile.failed)

    def test_progress_write_abort_does_not_attempt_error_event(self):
        h = self.handler(b"event: transfers")
        self.stream(h)
        self.assertTrue(h.wfile.failed)
        self.assertNotIn(b"transfer-error", h.wfile.getvalue())

    def test_headers_abort_is_quiet(self):
        h = self.handler(b"never")
        h.end_headers.side_effect = ConnectionAbortedError(10053, "aborted")
        self.stream(h)
        self.assertEqual(h.wfile.getvalue(), b"")

    def test_flush_abort_is_quiet(self):
        h = self.handler(b"never")
        h.wfile.flush = Mock(side_effect=ConnectionAbortedError(10053, "aborted"))
        self.stream(h)

    def test_real_upstream_error_still_emits_transfer_error(self):
        h = self.handler(b"never")
        h.wfile.flush = Mock(side_effect=[None, BrokenPipeError()])
        with (
            patch.object(realtime, "start"),
            patch.object(realtime.condition, "wait"),
            patch.object(
                realtime.transfer_progress,
                "snapshot",
                side_effect=ValueError("engine unavailable"),
            ),
        ):
            realtime.stream(h, server, "downloads")
        self.assertIn(b"event: transfer-error", h.wfile.getvalue())
        self.assertIn(b"engine unavailable", h.wfile.getvalue())

    def test_error_event_disconnect_does_not_retry_write(self):
        h = self.handler(b"event: transfer-error")
        with (
            patch.object(realtime, "start"),
            patch.object(realtime.condition, "wait"),
            patch.object(
                realtime.transfer_progress,
                "snapshot",
                side_effect=ValueError("engine unavailable"),
            ),
        ):
            realtime.stream(h, server, "downloads")
        self.assertTrue(h.wfile.failed)

    def test_api_error_does_not_log_or_reply_to_disconnected_browser(self):
        h = SimpleNamespace(send_json=Mock())
        with patch.object(server.diag, "error") as log:
            server.Handler.api_error(h, ConnectionAbortedError(10053, "aborted"))
        h.send_json.assert_not_called()
        log.assert_not_called()
        self.assertTrue(h.close_connection)

    def test_request_and_final_flush_boundaries_tolerate_disconnects(self):
        h = server.Handler.__new__(server.Handler)
        for exc in (
            BrokenPipeError(),
            ConnectionResetError(),
            ConnectionAbortedError(10053, "aborted"),
            TimeoutError(),
        ):
            with (
                self.subTest(error=type(exc).__name__),
                patch.object(BaseHTTPRequestHandler, "handle", side_effect=exc),
                patch.object(BaseHTTPRequestHandler, "finish", side_effect=exc),
            ):
                h.handle()
                h.finish()
                self.assertTrue(h.close_connection)

    def test_unexpected_request_errors_are_not_silenced(self):
        h = server.Handler.__new__(server.Handler)
        with patch.object(BaseHTTPRequestHandler, "handle", side_effect=RuntimeError("unexpected")):
            with self.assertRaises(RuntimeError):
                h.handle()


if __name__ == "__main__":
    unittest.main()
