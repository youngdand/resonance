import re, io, json, tempfile, threading, unittest, zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server, diagnostics as diag


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = server.DATA
        server.DATA = Path(self.tmp.name) / "data"
        server.init()
        self.key = "a-test-key-that-must-never-appear"
        with server.db() as c:
            c.execute("INSERT INTO settings VALUES (1,?)", (json.dumps({"key": self.key}),))

    def tearDown(self):
        for h in list(diag.logger.handlers):
            h.close()
            diag.logger.removeHandler(h)
        server.DATA = self.old
        server.diag.close()
        self.tmp.cleanup()

    def test_shutdown_releases_log_file_and_can_reconfigure(self):
        diag.event("before-close")
        path = server.DATA / "logs" / "resonance.log"
        diag.close()
        renamed = path.with_suffix(".closed")
        path.rename(renamed)
        self.assertEqual(diag.logger.handlers, [])
        diag.configure(server.DATA)
        diag.event("after-reopen")
        self.assertIn("after-reopen", path.read_text())

    def test_packaged_interface_and_service_versions_match(self):
        interface = (server.ROOT / "web" / "diagnostics.js").read_text()
        self.assertIn("window.RESONANCE_BUILD", interface)
        self.assertEqual((server.ROOT / "VERSION").read_text().strip(), diag.VERSION)
        self.assertIn("build.js", (server.ROOT / "web" / "index.html").read_text())

    def test_redaction_and_report_excludes_config(self):
        diag.event(
            "test-error",
            "ERROR",
            message="password=superprivate token=abc123 " + self.key + " " + server.TOKEN,
            localPath=r"C:\Users\Example\Secret\config.yml",
        )
        report = diag.report(
            server.ROOT,
            [
                {
                    "message": "api_key=" + self.key,
                    "time": "now",
                    "payload": "never include payload",
                }
            ],
        )
        with zipfile.ZipFile(io.BytesIO(report)) as z:
            content = "\n".join(z.read(n).decode() for n in z.namelist())
            self.assertIn("system.json", z.namelist())
            self.assertIn("browser-errors.json", z.namelist())
            self.assertFalse(any(n.endswith(".db") or n.endswith(".yml") for n in z.namelist()))
        for secret in [
            self.key,
            server.TOKEN,
            "superprivate",
            "abc123",
            "never include payload",
            r"C:\Users\Example",
        ]:
            self.assertNotIn(secret, content)

    def test_upstream_500_is_logged_with_route_and_redacted_body(self):
        error = HTTPError(
            "http://localhost:5030/api/v0/users/test/browse",
            500,
            "error",
            {},
            io.BytesIO(("password=secret " + self.key + " peer failed").encode()),
        )
        diag.begin("GET", "/api/browse?username=someone")
        with patch.object(server, "urlopen", side_effect=error):
            with self.assertRaisesRegex(ValueError, "HTTP 500"):
                server.slsk("users/test/browse")
        data = (server.DATA / "logs" / "resonance.log").read_text()
        self.assertIn("upstream-http-error", data)
        self.assertIn("users/{user}/browse", data)
        self.assertNotIn(self.key, data)
        self.assertNotIn("password=secret", data)

    def test_error_trace_is_saved_without_source_paths(self):
        try:
            raise ValueError("example diagnostic failure")
        except ValueError as e:
            diag.error(e, operation="unit-test")
        text = (server.DATA / "logs" / "resonance.log").read_text()
        self.assertIn("ValueError", text)
        self.assertIn("test_diagnostics.py", text)
        self.assertNotIn(str(Path(__file__).parent), text)

    def test_report_endpoint_and_unknown_api_return_json(self):
        h = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        t = threading.Thread(target=h.serve_forever, daemon=True)
        t.start()
        base = f"http://127.0.0.1:{h.server_port}"
        try:
            with urlopen(base + "/api/state") as r:
                state = json.load(r)
            self.assertEqual(state["version"], diag.VERSION)
            req = Request(
                base + "/api/diagnostics/download",
                data=json.dumps({"errors": [{"message": "test browser error"}]}).encode(),
                headers={
                    "Content-Type": "application/json",
                    "X-Resonance-Token": state["token"],
                },
            )
            with urlopen(req) as r:
                data = r.read()
                self.assertIn("zip", r.headers["Content-Type"])
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                self.assertIn("test browser error", z.read("browser-errors.json").decode())
            with self.assertRaises(HTTPError) as err:
                urlopen(base + "/api/nonexistent")
            self.assertEqual(err.exception.code, 404)
            body = json.load(err.exception)
            self.assertIn("requestId", body)
            self.assertIn("restart", body["error"].lower())
        finally:
            h.shutdown()
            h.server_close()
            t.join()


if __name__ == "__main__":
    unittest.main()
