"""Public bounty dataset cache warnings remain visible to API consumers."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cbh.hunt import discover
from cbh.api import _opportunity_details


class DiscoveryCacheWarningTests(unittest.TestCase):
    def test_discovery_reports_stale_cache_fallback(self):
        def fake_load(platform, refresh=False, cache_dir=None, opener=None, log=None):
            if log:
                log("warning: refresh failed (offline); using cached dataset")
            return [], "/tmp/hackerone_data.json"

        with patch("cbh.hunt.si.load_platform", side_effect=fake_load):
            results, warnings = discover(platforms=["hackerone"], refresh=True)

        self.assertEqual(results, [])
        self.assertTrue(any("using cached dataset" in warning for warning in warnings))

    def test_opportunity_details_marks_stale_scope_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "hackerone_data.json"
            cache_file.write_text("[]", encoding="utf-8")

            def fake_load(platform, refresh=False, cache_dir=None, opener=None, log=None):
                if log:
                    log("warning: refresh failed (offline); using cached dataset")
                return [], str(cache_file)

            with patch("cbh.scope_import.load_platform", side_effect=fake_load):
                rows = _opportunity_details([{
                    "platform": "hackerone",
                    "handle": "missing-program",
                }])

        details = rows[0]["details"]
        self.assertEqual(details["scope_cache"]["status"], "stale_fallback")
        self.assertIn("STALE PUBLIC DATASET CACHE", details["scope_source"])
        self.assertIn("using cached dataset", details["scope_cache"]["warning"])
        self.assertNotIn("authorization", details["scope_source"].lower())


if __name__ == "__main__":
    unittest.main()
