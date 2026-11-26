import tempfile
import unittest
from pathlib import Path
from cbh import automation


class AutomationTests(unittest.TestCase):
    def test_opportunities_persist_and_deduplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.sqlite3"
            item = {"platform": "hackerone", "handle": "sample", "name": "Sample", "score": 80}
            self.assertEqual(automation.record_opportunities([item], db), 1)
            self.assertEqual(automation.record_opportunities([item], db), 0)
            self.assertEqual(len(automation.list_opportunities(db)), 1)

    def test_ledger_income_expense(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.sqlite3"
            automation.add_transaction("income", 100, "USD", path=db)
            automation.add_transaction("expense", 10, "USD", path=db)
            totals = {(x["currency"], x["kind"]): x["total"] for x in automation.ledger_summary(db)}
            self.assertEqual(totals[("USD", "income")], 100)
            self.assertEqual(totals[("USD", "expense")], 10)

    def test_invalid_ledger_values_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.sqlite3"
            with self.assertRaises(ValueError):
                automation.add_transaction("income", -1, "USD", path=db)
            with self.assertRaises(ValueError):
                automation.add_transaction("income", 1, "US", path=db)


if __name__ == "__main__":
    unittest.main()
