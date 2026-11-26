import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cbh import assessment


class AssessmentTests(unittest.TestCase):
    def test_local_scan_saves_redacted_candidates_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sample.py").write_text(
                "value = eval(user_input)\n"
                "password = 'THIS_IS_A_FAKE_SECRET_VALUE_12345'\n",
                encoding="utf-8",
            )
            started, initial = assessment.start(root)
            self.assertTrue(started)
            self.assertEqual(initial["mode"], "local_only")
            self.assertEqual(initial["network_testing"], "BLOCKED")
            deadline = time.time() + 5
            state = assessment.status()
            while time.time() < deadline and state.get("status") in ("queued", "running"):
                time.sleep(0.02)
                state = assessment.status()
            self.assertEqual(state["status"], "completed", state)
            self.assertEqual(state["simulation"]["network_requests"], 0)
            self.assertFalse(state["simulation"]["executed_target_code"])
            self.assertTrue(Path(state["report"]).is_file())
            findings = state["findings"]
            self.assertTrue(any(x["category"] == "dynamic_code_execution" for x in findings))
            secret = next(x for x in findings if x["category"] == "possible_token_assignment")
            self.assertEqual(secret["snippet"], "[POTENTIAL SECRET REDACTED]")
            self.assertEqual(len(assessment.history(root)), 1)

    def test_assessment_deduplicates_identical_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("eval(x)\neval(x)\n", encoding="utf-8")
            result = assessment._scan(root, "dedupe-test")
            self.assertEqual(len(result["findings"]), 1)

    def test_scan_excludes_git_and_dependency_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            (root / ".git" / "bad.py").write_text("eval(x)\n", encoding="utf-8")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "bad.py").write_text("eval(x)\n", encoding="utf-8")
            result = assessment._scan(root, "skip-test")
            self.assertEqual(result["files_scanned"], 0)
            self.assertEqual(result["findings"], [])


if __name__ == "__main__":
    unittest.main()
