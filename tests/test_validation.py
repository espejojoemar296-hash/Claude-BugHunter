import json
import tempfile
import unittest
from pathlib import Path
from cbh.validation import validate_finding


class ValidationTests(unittest.TestCase):
    def setup_case(self, root):
        scope = root / "scope.md"
        scope.write_text(
            "## In scope\n- example.test\n## Out of scope\n- admin.example.test\n",
            encoding="utf-8",
        )
        evidence = root / "evidence"
        evidence.mkdir()
        (evidence / "request.txt").write_text(
            "GET /api HTTP/1.1\nHost: app.example.test\n\n", encoding="utf-8"
        )
        (evidence / "response.txt").write_text(
            "HTTP/1.1 200 OK\nContent-Type: text/plain\n\nok\n", encoding="utf-8"
        )
        manifest = evidence / "manifest.json"
        manifest.write_text(json.dumps({
            "version": 1, "target": "https://app.example.test/api",
            "reproduction": {"status": "REPRODUCED"},
            "artifacts": [
                {"type": "http_request", "path": "request.txt"},
                {"type": "http_response", "path": "response.txt"},
            ],
        }), encoding="utf-8")
        return scope, manifest

    def test_valid_scope_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scope, manifest = self.setup_case(root)
            result = validate_finding(
                root / "finding.md", {"asset": "https://app.example.test/api"},
                manifest, scope,
            )
            self.assertEqual(result["scope"], "PASS")
            self.assertEqual(result["artifacts"], "PASS")
            self.assertEqual(result["status"], "READY_FOR_REVIEW")

    def test_out_of_scope_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scope, manifest = self.setup_case(root)
            result = validate_finding(
                root / "finding.md", {"asset": "https://admin.example.test/api"},
                manifest, scope,
            )
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["scope"], "FAIL")

    def test_artifact_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scope, manifest = self.setup_case(root)
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["artifacts"][0]["path"] = "../scope.md"
            manifest.write_text(json.dumps(data), encoding="utf-8")
            result = validate_finding(
                root / "finding.md", {"asset": "https://app.example.test/api"},
                manifest, scope,
            )
            self.assertEqual(result["artifacts"], "FAIL")
            self.assertIn("escapes", result["reasons"][0])

    def test_missing_scope_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = validate_finding(
                root / "finding.md", {"asset": "https://app.example.test"},
                root / "missing.json", root / "missing-scope.md",
            )
            self.assertEqual(result["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
