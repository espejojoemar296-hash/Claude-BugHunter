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

    def test_opportunity_discovery_status_is_available(self):
        status, payload = self.request("/opportunities/status")
        self.assertEqual(status, 200)
        self.assertIn(payload["status"], ("idle", "running", "completed", "failed"))

    def test_opportunity_refresh_runs_in_background(self):
        import time
        from unittest.mock import patch

        body = b"{}"
        req = Request(
            self.base + "/opportunities/refresh", data=body, method="POST",
            headers={"Authorization": "Bearer test-secret", "Content-Type": "application/json"},
        )
        with patch("cbh.hunt.discover", return_value=([{"handle": "demo"}], [])), \
             patch("cbh.api.automation.record_opportunities", return_value=1):
            with urlopen(req, timeout=3) as response:
                self.assertEqual(response.status, 202)
            deadline = time.time() + 2
            payload = {}
            while time.time() < deadline:
                _, payload = self.request("/opportunities/status")
                if payload.get("status") in ("completed", "failed"):
                    break
                time.sleep(0.01)

        self.assertEqual(payload.get("status"), "completed")
        self.assertEqual(payload.get("checked"), 1)
        self.assertEqual(payload.get("added"), 1)


    def test_opportunities_include_published_scope_details(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        rows = [{"platform": "hackerone", "handle": "demo", "name": "Demo"}]
        record = {"name": "Demo", "targets": {}}
        entry = SimpleNamespace(
            raw="app.example.test", asset_type="URL", status="rule",
            side="in", bounty=True, severity="high", instruction="",
            reason="", rules=[r"re:^app\.example\.test$"],
        )
        program = SimpleNamespace(entries=[entry], conduct=["No denial of service"])
        with patch("cbh.automation.list_opportunities", return_value=rows):
            with patch("cbh.scope_import.load_platform", return_value=([record], "cache")):
                with patch("cbh.scope_import._record_handle", return_value="demo"):
                    with patch("cbh.scope_import.program_from_record", return_value=program):
                        from cbh.api import _opportunity_details
                        result = _opportunity_details(rows)

        self.assertEqual(result[0]["details"]["in_scope"][0]["asset"], "app.example.test")
        self.assertEqual(result[0]["details"]["out_of_scope"], [])
        self.assertEqual(result[0]["details"]["conduct"], ["No denial of service"])

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

    def test_workspace_includes_external_audit_and_verification_summary(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from cbh.api import _workspace_snapshot

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Claude-BugHunter"
            root.mkdir()
            audit = Path(tmp) / "audits" / "cli" / "source-scan-v4.0-report.json"
            audit.parent.mkdir(parents=True)
            audit.write_text(json.dumps({
                "scanner": "test scanner", "version": "4.0",
                "created_at": "2026-11-27T00:00:00Z",
                "files_scanned": 12, "finding_count": 3,
                "limitations": ["heuristic only"],
            }), encoding="utf-8")
            workspaces = Path(tmp) / "verification" / "cli-v1" / "finding_workspaces"
            workspaces.mkdir(parents=True)
            (workspaces / "finding-0001").mkdir()
            (workspaces / "finding-0001" / "finding.json").write_text(
                json.dumps({"verification_status": "NOT_TESTED"}), encoding="utf-8"
            )
            with patch("cbh.api.Path.cwd", return_value=root), patch("cbh.api.Path.home", return_value=root):
                snapshot = _workspace_snapshot()

        self.assertTrue(snapshot["audit_summary"]["available"])
        self.assertEqual(snapshot["audit_summary"]["finding_count"], 3)
        self.assertEqual(snapshot["verification_status_counts"], {"NOT_TESTED": 1})

    def test_api_refuses_non_loopback_binding(self):
        from cbh.api import serve
        with self.assertRaises(ValueError):
            serve(host="0.0.0.0", port=8765)


if __name__ == "__main__":
    unittest.main()
