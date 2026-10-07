"""Standalone release-harness checks; only the adjacent smoke script is needed."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import runpy
import tempfile
import threading
import unittest
import urllib.request


CHECK = runpy.run_path(str(Path(__file__).with_name("windows_release_smoke.py")))[
    "check_investigation_asset_file"]
APP = ('<button id="openinvestigation"></button>'
       '<h2 id="investigation-title"></h2>'
       '<script src="/investigation.js"></script>')
LINES = ["// Byte-preserving release check: 中文", "global.GeoForgeInvestigation={create}", ""]


@contextmanager
def served_script(payload: bytes):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{server.server_port}/investigation.js", timeout=5) as response:
            yield response.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class ReleaseAssetBytesTests(unittest.TestCase):
    def compare(self, stored: bytes, served: bytes):
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / "investigation.js"
            script.write_bytes(stored)
            with served_script(served) as fetched:
                CHECK(APP, fetched, script)
            self.assertEqual(script.read_bytes(), stored)

    def test_identical_lf_http_payload_passes(self):
        payload = "\n".join(LINES).encode("utf-8")
        self.compare(payload, payload)

    def test_identical_crlf_http_payload_passes(self):
        payload = "\r\n".join(LINES).encode("utf-8")
        self.compare(payload, payload)

    def test_different_newlines_are_still_rejected(self):
        lf = "\n".join(LINES).encode("utf-8")
        crlf = "\r\n".join(LINES).encode("utf-8")
        with self.assertRaisesRegex(AssertionError, "payload differs"):
            self.compare(crlf, lf)

    def test_changed_http_payload_is_rejected(self):
        payload = "\r\n".join(LINES).encode("utf-8")
        with self.assertRaisesRegex(AssertionError, "payload differs"):
            self.compare(payload, payload + b"// stale or changed asset\r\n")


if __name__ == "__main__":
    unittest.main()
