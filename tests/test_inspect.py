import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cbh.inspect import ORIGIN, _safe_url, cors_signal, inspect_url


class FakeScope:
    def reject_reason(self, target):
        return "not explicitly authorized"


class InspectTests(unittest.TestCase):
    def test_rejects_non_http_scheme(self):
        with self.assertRaises(ValueError):
            _safe_url("ftp://example.test/")

    def test_rejects_nonstandard_port(self):
        with self.assertRaises(ValueError):
            _safe_url("https://example.test:8443/")

    def test_rejects_embedded_credentials(self):
        with self.assertRaises(ValueError):
            _safe_url("https://user:pass@example.test/")

    def test_normalizes_empty_path(self):
        self.assertEqual(_safe_url("https://example.test"), "https://example.test/")

    def test_detects_credentialed_origin_reflection_candidate(self):
        result = cors_signal({
            "Access-Control-Allow-Origin": ORIGIN,
            "Access-Control-Allow-Credentials": "true",
        })
        self.assertTrue(result["candidate"])

    def test_wildcard_is_not_origin_reflection(self):
        result = cors_signal({
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Credentials": "true",
        })
        self.assertFalse(result["candidate"])

    def test_scope_blocks_before_network_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            scope_file = Path(tmp) / "scope.md"
            scope_file.write_text("# scope\n", encoding="utf-8")
            with patch("cbh.inspect._load_scope", return_value=FakeScope()):
                with patch("cbh.inspect.urllib.request.build_opener") as opener:
                    with self.assertRaises(PermissionError):
                        inspect_url("https://outside.example.test/", str(scope_file), str(Path(tmp) / "out"))
                    opener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
