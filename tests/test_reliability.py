"""全程完成机会与交接损失报告测试。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unittest

from yanxue.book import load
from yanxue.evidence import build_chains
from yanxue.reliability import reliability_report

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "samples.json"


class ReliabilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chains = build_chains(load(SAMPLE))

    def test_completion_is_a_range_not_a_point_multiply(self):
        report = reliability_report(self.chains)
        day1 = next(c for c in report["cohorts"] if c["day"] == "2026-11-14")
        # A、B 都可能完成，但没有一条全程确定
        self.assertEqual(day1["completion"]["count_range"], [0, 2])
        self.assertEqual(day1["completion"]["rate_range"], [0.0, 1.0])
        self.assertIn("不使用各站独立准点率相乘", report["method"])

    def test_open_and_early_ended_are_separate_from_failure(self):
        report = reliability_report(self.chains)
        day2 = next(c for c in report["cohorts"] if c["day"] == "2026-11-15")
        self.assertEqual(day2["losses"]["failed"], [])
        self.assertEqual(day2["losses"]["early_ended"], ["C"])
        self.assertEqual(day2["unobserved"], ["D"])

    def test_filters_origin_rest_version(self):
        report = reliability_report(self.chains, origin="东门", rest_min=20)
        groups = {g for c in report["cohorts"] for g in c["groups"]}
        self.assertEqual(groups, {"A"})
        v2 = reliability_report(self.chains, version="v2")
        self.assertEqual(v2["group_count"], 3)

    def test_blocked_comparison_for_shared_receipt(self):
        report = reliability_report(self.chains)
        shared = [b for b in report["blocked_comparisons"] if b["type"] == "共享待定凭证"]
        self.assertTrue(any(set(b["groups"]) == {"A", "B"} for b in shared))

    def test_unobserved_groups_cannot_be_compared(self):
        report = reliability_report(self.chains)
        open_blocks = [b for b in report["blocked_comparisons"] if b["type"] == "结局未观察"]
        blocked_groups = {g for b in open_blocks for g in b["groups"]}
        self.assertIn("E", blocked_groups)
        self.assertIn("D", blocked_groups)


if __name__ == "__main__":
    unittest.main()
