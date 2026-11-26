import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cbh import hunt


def entry(side="in", status="rule", asset_type="URL", bounty=True):
    return SimpleNamespace(
        side=side, status=status, asset_type=asset_type, bounty=bounty
    )


class HuntTests(unittest.TestCase):
    def test_hackerone_reward_flag(self):
        label, eligible = hunt._reward(
            "hackerone", {"offers_bounties": True}
        )
        self.assertTrue(eligible)
        self.assertIn("Bounty offered", label)

    def test_hackerone_without_bounties(self):
        _, eligible = hunt._reward(
            "hackerone", {"offers_bounties": False}
        )
        self.assertFalse(eligible)

    def test_intigriti_reward_includes_currency(self):
        label, eligible = hunt._reward("intigriti", {
            "min_bounty": {"value": 50, "currency": "EUR"},
            "max_bounty": {"value": 1500, "currency": "EUR"},
        })
        self.assertTrue(eligible)
        self.assertIn("EUR", label)
        self.assertIn("50", label)
        self.assertIn("1500", label)

    def test_bugcrowd_reward_does_not_invent_currency(self):
        label, eligible = hunt._reward("bugcrowd", {"max_payout": 5000})
        self.assertTrue(eligible)
        self.assertIn("currency unspecified", label)

    def test_yeswehack_reward_does_not_invent_currency(self):
        label, eligible = hunt._reward(
            "yeswehack", {"min_bounty": 50, "max_bounty": 5000}
        )
        self.assertTrue(eligible)
        self.assertIn("currency unspecified", label)

    def test_bugcrowd_status_is_unknown(self):
        label, status = hunt._availability("bugcrowd", {})
        self.assertIsNone(status)
        self.assertIn("not supplied", label)

    def test_yeswehack_must_be_public_and_enabled(self):
        _, status = hunt._availability(
            "yeswehack", {"public": True, "disabled": False}
        )
        self.assertTrue(status)

        _, status = hunt._availability(
            "yeswehack", {"public": True, "disabled": True}
        )
        self.assertFalse(status)

    def test_asset_counts_separate_review_and_non_web_assets(self):
        program = SimpleNamespace(entries=[
            entry(asset_type="URL"),
            entry(asset_type="API"),
            entry(asset_type="SOURCE_CODE"),
            entry(status="review", asset_type="URL"),
            entry(side="out", asset_type="URL"),
        ])
        self.assertEqual(hunt._asset_counts(program), (3, 1, 2, 3))

    def test_score_distinguishes_different_asset_coverage(self):
        smaller = hunt._score(True, 10, 0, 8, True)
        larger = hunt._score(True, 40, 0, 30, True)
        self.assertGreater(larger, smaller)
        self.assertLessEqual(larger, 100)

    def test_manual_review_reduces_score(self):
        clear = hunt._score(True, 10, 0, 8, True)
        unclear = hunt._score(True, 10, 4, 8, True)
        self.assertGreater(clear, unclear)

    def test_discover_filters_and_ranks(self):
        records = [
            {"handle": "small", "name": "Small Program",
             "offers_bounties": True, "submission_state": "open"},
            {"handle": "large", "name": "Large Program",
             "offers_bounties": True, "submission_state": "open"},
        ]

        def fake_program(platform, record):
            count = 8 if record["handle"] == "small" else 30
            return SimpleNamespace(entries=[
                entry(asset_type="URL") for _ in range(count)
            ])

        with patch.object(hunt.si, "load_platform",
                          return_value=(records, "/tmp/cache.json")), \
             patch.object(hunt.si, "program_from_record",
                          side_effect=fake_program):
            results, warnings = hunt.discover(
                platforms=["hackerone"], bounty_only=True, limit=10
            )

        self.assertEqual(warnings, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["handle"], "large")

    def test_search_filters_by_name_or_handle(self):
        records = [
            {"handle": "alpha", "name": "Alpha Program",
             "offers_bounties": True, "submission_state": "open"},
            {"handle": "beta", "name": "Beta Program",
             "offers_bounties": True, "submission_state": "open"},
        ]

        with patch.object(hunt.si, "load_platform",
                          return_value=(records, "/tmp/cache.json")), \
             patch.object(hunt.si, "program_from_record",
                          return_value=SimpleNamespace(entries=[])):
            results, _ = hunt.discover(
                platforms=["hackerone"], search="beta"
            )

        self.assertEqual([r["handle"] for r in results], ["beta"])


if __name__ == "__main__":
    unittest.main()
