"""Transport contracts: verify policy before dispatch without contacting suppliers."""

import concurrent.futures
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request
from io import BytesIO
import supplier_http as http


class SupplierPolicyTests(unittest.TestCase):
    def setUp(self):
        self.online = True
        self.s = SimpleNamespace(
            settings=lambda _: {"discoveryOnline": self.online},
            diag=SimpleNamespace(VERSION="1.0.0-rc.1"),
        )
        http.last.clear()
        http.cooldowns.clear()

    def test_offline_rejects_before_opening_connection(self):
        self.online = False
        with patch.object(http, "build_opener") as opener:
            with self.assertRaisesRegex(ValueError, "stopped"):
                http.read(self.s, "https://itunes.apple.com/search?term=fixture")
            opener.assert_not_called()

    def test_redirect_target_and_consent_checked_before_dispatch(self):
        def inspect(handler):
            with self.assertRaisesRegex(ValueError, "redirect"):
                handler.redirect_request(
                    Request("https://itunes.apple.com/search"),
                    None,
                    302,
                    "",
                    {},
                    "https://example.com/steal",
                )
            self.online = False
            with self.assertRaisesRegex(ValueError, "stopped"):
                handler.redirect_request(
                    Request("https://itunes.apple.com/search"),
                    None,
                    302,
                    "",
                    {},
                    "https://itunes.apple.com/other",
                )
            raise ValueError("inspected")

        with patch.object(http, "build_opener", side_effect=inspect):
            with self.assertRaisesRegex(ValueError, "inspected"):
                http.read(self.s, "https://itunes.apple.com/search")

    def test_simultaneous_identical_requests_share_one_connection(self):
        entered = threading.Event()
        release = threading.Event()

        def open_response(*args, **kwargs):
            entered.set()
            release.wait(2)
            return BytesIO(b"{}")

        opener = SimpleNamespace(open=open_response)
        with (
            patch.object(http, "build_opener", return_value=opener) as opened,
            concurrent.futures.ThreadPoolExecutor(2) as pool,
        ):
            a = pool.submit(http.read, self.s, "https://api.deezer.com/album/fixture")
            self.assertTrue(entered.wait(2))
            b = pool.submit(http.read, self.s, "https://api.deezer.com/album/fixture")
            time.sleep(0.05)
            release.set()
            self.assertEqual(a.result(), b"{}")
            self.assertEqual(b.result(), b"{}")
            self.assertEqual(opened.call_count, 1)

    def test_busy_supplier_cools_down_without_second_dispatch(self):
        opener = SimpleNamespace(
            open=lambda *a, **k: (_ for _ in ()).throw(
                HTTPError("https://api.deezer.com/x", 503, "busy", {"Retry-After": "120"}, None)
            )
        )
        with patch.object(http, "build_opener", return_value=opener) as opened:
            with self.assertRaises(HTTPError):
                http.read(self.s, "https://api.deezer.com/x")
            with self.assertRaisesRegex(ValueError, "cooling down"):
                http.read(self.s, "https://api.deezer.com/y")
            self.assertEqual(opened.call_count, 1)

    def test_response_and_url_bounds(self):
        with patch.object(
            http,
            "build_opener",
            return_value=SimpleNamespace(open=lambda *a, **k: BytesIO(b"12345")),
        ):
            with self.assertRaisesRegex(ValueError, "size limit"):
                http.read(self.s, "https://api.deezer.com/x", limit=4)
        for url in [
            "http://api.deezer.com/x",
            "https://user:secret@api.deezer.com/x",
            "https://api.deezer.com:999/x",
            "https://example.com/x",
        ]:
            with self.assertRaises(ValueError):
                http.read(self.s, url)
