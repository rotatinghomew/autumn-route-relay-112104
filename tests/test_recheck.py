"""补证复检测试。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import copy
import unittest

from yanxue.book import load
from yanxue.evidence import build_chains
from yanxue.ledger import init_ledger
from yanxue.recheck import recheck

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "samples.json"


class RecheckTest(unittest.TestCase):
    def setUp(self):
        self.before = load(SAMPLE)
        self.after = copy.deepcopy(self.before)
        self.ledger = init_ledger(self.before)

    def test_new_receipt_changes_conclusion_and_protects_history(self):
        # 补回 A 的返车确定凭证
        self.after["stations"].append(
            {"ref": "p9", "group_choices": ["A"], "station": "返车",
             "in_at": "12:03", "out_at": "12:06", "known_seq": 4}
        )
        result = recheck(self.before, self.after, self.ledger)
        changed = {item["group"]: item for item in result["changed"]}
        self.assertIn("A", changed)
        self.assertEqual(changed["A"]["to"]["completion"], "全程完成")
        self.assertIn("B", result["unchanged"])

        # 历史签发不被改写
        current = init_ledger(self.before)
        self.assertEqual(
            [c["commitment_id"] for c in self.ledger["commitments"]],
            [c["commitment_id"] for c in current["commitments"]],
        )

        entry = next(g for g in result["recheck_groups"] if g["group"] == "A")
        self.assertTrue(entry["readiness"]["known"])
        slots = {o["slot"] for o in entry["open_options"]}
        self.assertIn("车甲", slots)

    def test_irrelevant_receipt_changes_nothing(self):
        self.after["stations"].append(
            {"ref": "p10", "group_choices": ["E"], "station": "讲堂",
             "in_at": "09:12", "out_at": "10:00", "known_seq": 3}
        )
        result = recheck(self.before, self.after, self.ledger)
        # E 仍未观察到全程，其余团不变
        self.assertEqual(result["changed"], [])

    def test_ambiguous_to_certain_resolves_shared_receipt(self):
        # 给 B 补一条实践室确定凭证，p3 不再需要分担
        self.after["stations"].append(
            {"ref": "p11", "group_choices": ["B"], "station": "实践室",
             "in_at": "10:40", "out_at": "11:25", "known_seq": 4}
        )
        chains = build_chains(self.after)
        b_room = next(v for v in chains["B"]["visits"] if v["station"] == "实践室")
        self.assertEqual(b_room["attribution"], "确定")
        result = recheck(self.before, self.after, self.ledger)
        self.assertIn("B", {item["group"] for item in result["changed"]})


if __name__ == "__main__":
    unittest.main()
