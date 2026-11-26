import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cbh.engagement import run_approved_engagement


class ApprovedEngagementTests(unittest.TestCase):
    def _fixture(self, root, target="localhost:3002"):
        scope = root / "scope.md"
        scope.write_text(
            "# Scope - local test\n\n## In scope\n- localhost\n\n## Out of scope\n- admin.localhost\n",
            encoding="utf-8",
        )
        config = root / "approved.json"
        config.write_text(json.dumps({
            "name": "local-test",
            "target": target,
            "scope_file": "scope.md",
            "seeds": ["http://localhost:3002"],
        }), encoding="utf-8")
        return config

    def test_out_of_scope_target_is_rejected_before_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._fixture(Path(tmp), "evil.example")
            with self.assertRaisesRegex(ValueError, "not authorized"):
                run_approved_engagement(config, mock=True)

    def test_out_of_scope_seed_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._fixture(Path(tmp))
            data = json.loads(config.read_text(encoding="utf-8"))
            data["seeds"] = ["https://admin.localhost/"]
            config.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "seed is not authorized"):
                run_approved_engagement(config, mock=True)

    def test_missing_claude_cli_stops_before_network_activity(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._fixture(Path(tmp))
            with patch("cbh.engagement.shutil.which", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "No target requests were sent"):
                    run_approved_engagement(config, mock=False)

    def test_mock_full_pipeline_writes_report_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._fixture(Path(tmp))
            result = run_approved_engagement(config, mock=True, base=Path(tmp) / "runs")
            self.assertTrue(result["ok"])
            report = Path(result["report"])
            self.assertTrue(report.is_file())
            self.assertIn("Engagement report", report.read_text(encoding="utf-8"))
            self.assertTrue(result["mock"])


if __name__ == "__main__":
    unittest.main()
