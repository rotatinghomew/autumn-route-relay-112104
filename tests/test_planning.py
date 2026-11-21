"""台账、试算与签发测试。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import copy
import unittest
from pathlib import Path

from yanxue.book import load
from yanxue.evidence import build_chains
from yanxue.ledger import (
    ACCEPTED,
    ACTIVE,
    PENDING,
    SIGNED,
    SUPERSEDED,
    capacity_view,
    init_ledger,
)
from yanxue.planning import audit_group, evaluate_scenario, issue_scenario, readiness

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "samples.json"


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.book = load(SAMPLE)
        self.chains = build_chains(self.book)
        self.ledger = init_ledger(self.book)

    def test_notices_split_into_three_placements(self):
        kinds = {(c["group"], c["kind"], c["slot"], c["status"]) for c in self.ledger["commitments"]}
        self.assertIn(("A", SIGNED, "车甲", ACTIVE), kinds)
        self.assertIn(("A", PENDING, "补一", ACTIVE), kinds)
        self.assertIn(("D", SIGNED, "补三", SUPERSEDED), kinds)
        self.assertIn(("D", ACCEPTED, "补二", ACTIVE), kinds)
        self.assertIn(("B", SIGNED, "车甲", ACTIVE), kinds)

    def test_capacity_counts_signed_accepted_and_pending(self):
        view = {row["slot"]: row for row in capacity_view(self.book, self.ledger)}
        self.assertEqual(view["车甲"]["committed_seats"], 9)
        self.assertEqual(view["车甲"]["remaining_conservative"], 1)
        # 补一：待确认改签保守占 5 人
        self.assertEqual(view["补一"]["pending_held_seats"], 5)
        self.assertEqual(view["补一"]["remaining_conservative"], 3)
        self.assertEqual(view["补一"]["remaining_if_pending_rejected"], 8)
        # 补二：已接受替代占 3 人
        self.assertEqual(view["补二"]["committed_seats"], 3)
        self.assertEqual(view["补二"]["remaining_conservative"], 2)

    def test_readiness_combines_walk_and_care_interval(self):
        ready = readiness(self.chains["A"])
        self.assertTrue(ready["known"])
        # 实践室 11:38 离开，步行 10 -> 11:48；rest 20 -> 11:58
        self.assertEqual(ready["walk_ready"], "11:48")
        self.assertEqual(ready["rest_ready"], "11:58")
        self.assertEqual(ready["earliest_board"], "11:58")

    def test_early_bus_can_squeeze_care_interval(self):
        # A 最早 11:58 才能登车，车乙 11:48 违反照护间隔；车甲 12:00 可行
        sc = {"scenario": "early", "groups": ["A", "B"],
              "assignments": {"A": "车乙", "B": "车乙"}}
        result = evaluate_scenario(self.book, self.chains, self.ledger, sc)
        a = next(g for g in result["group_results"] if g["group"] == "A")
        self.assertTrue(any("照护间隔" in r for r in a["blocked_reasons"]))
        self.assertFalse(result["executable"])

    def test_pending_protocol_is_not_executable_and_keeps_placeholder(self):
        sc = {"scenario": "pending", "groups": ["A", "B"],
              "assignments": {"A": "补一", "B": "车甲"}}
        result = evaluate_scenario(self.book, self.chains, self.ledger, sc)
        # B 的实践室凭证待定：证据缺口足以反转，不可签发
        self.assertTrue(result["evidence_gap"])
        self.assertFalse(result["executable"])
        # 原承诺仍在车甲占位
        self.assertTrue(
            any(c["group"] == "A" and c["slot"] == "车甲" and c["status"] == ACTIVE
                for c in self.ledger["commitments"])
        )

    def test_accepted_protocol_allows_issuance_and_supersedes(self):
        book = copy.deepcopy(self.book)
        # 先给 B 补一条实践室确定凭证，消除待定归属带来的证据缺口
        book["stations"].append(
            {"ref": "p11", "group_choices": ["B"], "station": "实践室",
             "in_at": "10:40", "out_at": "11:25", "known_seq": 4}
        )
        book["notices"] = [
            {"notice": "N9", "group": "B", "slot": "车甲", "size": 4,
             "alternate": "补一", "accepted": "补一", "seq": 1}
        ]
        chains = build_chains(book)
        ledger = init_ledger(book)
        sc = {"scenario": "move-b", "groups": ["B"], "assignments": {"B": "补一"}}
        result = evaluate_scenario(book, chains, ledger, sc)
        self.assertTrue(result["executable"])
        issue = issue_scenario(book, chains, ledger, result, sc)
        self.assertEqual(issue["status"], "issued")
        original = next(c for c in ledger["commitments"] if c["kind"] == SIGNED)
        alternate = next(c for c in ledger["commitments"] if c["kind"] == ACCEPTED)
        self.assertEqual(original["status"], SUPERSEDED)
        self.assertEqual(alternate["slot"], "补一")
        self.assertEqual(alternate["status"], ACTIVE)

    def test_cross_day_offer_rejected(self):
        sc = {"scenario": "cross", "groups": ["D"], "assignments": {"D": "补一"}}
        result = evaluate_scenario(self.book, self.chains, self.ledger, sc)
        reasons = result["group_results"][0]["blocked_reasons"]
        self.assertTrue(any("另日场次" in r for r in reasons))
        self.assertFalse(result["executable"])

    def test_shared_slot_capacity_used_once_and_overbook_detected(self):
        book = copy.deepcopy(self.book)
        book["offers"] = [
            {"option": "标准", "slot": "车甲", "day": "2026-11-14", "time": "12:00",
             "capacity": 8, "eligible_groups": ["A", "B"]}
        ]
        # 两团都持车甲原签发，维持方案时需求应按团各计一次、容量只扣一次
        book["notices"] = [
            {"notice": "N1", "group": "A", "slot": "车甲", "size": 5,
             "alternate": None, "accepted": None, "seq": 1},
            {"notice": "N3", "group": "B", "slot": "车甲", "size": 4,
             "alternate": None, "accepted": None, "seq": 2},
        ]
        ledger = init_ledger(book)
        sc = {"scenario": "squeeze", "groups": ["A", "B"],
              "assignments": {"A": "车甲", "B": "车甲"}}
        result = evaluate_scenario(book, self.chains, ledger, sc)
        # A 5 + B 4 = 9 > 8
        self.assertTrue(result["slot_usage"]["车甲"]["overbooked"])
        self.assertEqual(result["slot_usage"]["车甲"]["demand_seats"], 9)
        self.assertFalse(result["executable"])

    def test_audit_lists_basis_options_and_reasons(self):
        audit = audit_group(self.book, self.chains, self.ledger, "D")
        self.assertEqual(audit["readiness"]["known"], False)
        self.assertTrue(any("无到达凭证" in r for r in audit["readiness"]["reasons"]))
        slots = {o["slot"] for o in audit["options"]}
        self.assertIn("补二", slots)
        self.assertNotIn("车甲", slots)  # 另日/不符合资格的场次不进选择


if __name__ == "__main__":
    unittest.main()
