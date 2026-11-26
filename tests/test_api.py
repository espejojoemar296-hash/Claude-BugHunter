import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from cbh.api import make_handler


class LocalApiTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler("test-secret"))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:" + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, path, token="test-secret"):
        req = Request(self.base + path, headers={"Authorization": "Bearer " + token})
        with urlopen(req, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_health_requires_token(self):
        self.assertEqual(self.request("/health")[1]["service"], "claude-bughunter")
        req = Request(self.base + "/health")
        with self.assertRaises(HTTPError) as caught:
            urlopen(req, timeout=3)
        self.assertEqual(caught.exception.code, 401)

    def test_unknown_route_is_not_found(self):
        req = Request(self.base + "/missing", headers={"Authorization": "Bearer test-secret"})
        with self.assertRaises(HTTPError) as caught:
            urlopen(req, timeout=3)
        self.assertEqual(caught.exception.code, 404)
        payload = json.loads(caught.exception.read().decode("utf-8"))
        self.assertEqual(payload["error"], "not_found")

    def test_engagement_status_requires_token_and_is_available(self):
        status, payload = self.request("/engagement/status")
        self.assertEqual(status, 200)
        self.assertIn(payload["status"], ("idle", "running", "completed", "failed"))

    def test_engagement_run_rejects_path_traversal(self):
        body = json.dumps({"config": "../outside.json"}).encode("utf-8")
        req = Request(
            self.base + "/engagement/run", data=body, method="POST",
            headers={"Authorization": "Bearer test-secret", "Content-Type": "application/json"},
        )
        with self.assertRaises(HTTPError) as caught:
            urlopen(req, timeout=3)
        self.assertEqual(caught.exception.code, 400)

    def test_workspace_includes_engagement_report_drafts(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from cbh.api import _workspace_snapshot

        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / ".bughunter-engagements" / "acme" / "report.md"
            report.parent.mkdir(parents=True)
            report.write_text("# Draft", encoding="utf-8")
            with patch("cbh.api.Path.home", return_value=Path(tmp)):
                snapshot = _workspace_snapshot()
            self.assertTrue(any(item["path"] == str(report) for item in snapshot["reports"]))

    def test_workspace_shows_scope_for_each_approved_target(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from cbh.api import _workspace_snapshot

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            approved = root / "targets" / "approved"
            scopes = root / "scopes"
            approved.mkdir(parents=True)
            scopes.mkdir()
            scope = scopes / "acme.md"
            scope.write_text("# Acme scope\\n\\n## In scope\\n- app.example.com\\n", encoding="utf-8")
            (approved / "acme.json").write_text(json.dumps({
                "target": "app.example.com", "scope_file": "../../scopes/acme.md"
            }), encoding="utf-8")
            with patch("cbh.api.Path.cwd", return_value=root), patch("cbh.api.Path.home", return_value=root):
                snapshot = _workspace_snapshot()
            self.assertEqual(snapshot["approved_targets"][0]["scope_preview"], scope.read_text(encoding="utf-8"))

    def test_api_refuses_non_loopback_binding(self):
        from cbh.api import serve
        with self.assertRaises(ValueError):
            serve(host="0.0.0.0", port=8765)


if __name__ == "__main__":
    unittest.main()
