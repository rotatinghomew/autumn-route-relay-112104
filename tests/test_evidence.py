"""证据归属与全程联程测试。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unittest

from yanxue.book import load
from yanxue.evidence import (
    AMBIGUOUS,
    ARRIVED,
    BROKEN,
    CERTAIN,
    MISSING,
    OK,
    OPEN,
    POSSIBLE,
    build_chains,
)
from pathlib import Path

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "samples.json"


class EvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chains = build_chains(load(SAMPLE))

    def test_ambiguous_receipt_is_not_duplicated(self):
        # p3 同时撞 A、B：A 另有确定凭证 p5，p3 对 B 保持待定，绝不复制成两次到达
        a_room = next(v for v in self.chains["A"]["visits"] if v["station"] == "实践室")
        b_room = next(v for v in self.chains["B"]["visits"] if v["station"] == "实践室")
        self.assertEqual(a_room["attribution"], CERTAIN)
        self.assertEqual(a_room["arrival"], ARRIVED)
        self.assertEqual(b_room["attribution"], AMBIGUOUS)
        self.assertEqual(b_room["arrival"], POSSIBLE)
        p3_for_b = next(e for e in b_room["evidence"] if e["ref"] == "p3")
        self.assertEqual(p3_for_b["shared_with"], ["A"])

    def test_missing_out_at_gets_range_not_absence(self):
        # A 的讲堂出站缺报，但实践室确定到达：离开时刻给范围
        hall = next(v for v in self.chains["A"]["visits"] if v["station"] == "讲堂")
        self.assertIsNone(hall["out_at"])
        self.assertEqual(hall["out_range"], ["09:03", "10:56"])
        self.assertEqual(hall["out_range_basis"], "下一站确定凭证")
        self.assertEqual(hall["arrival"], ARRIVED)

    def test_handover_uses_range_lower_bound_and_can_hold(self):
        handovers = self.chains["A"]["handovers"]
        first = handovers[0]
        self.assertEqual(first["status"], OK)
        self.assertEqual(first["depart_basis"], "缺报范围下界")
        # 返车无凭证：未观察，而不是失败
        self.assertEqual(handovers[1]["status"], OPEN)

    def test_states_are_never_all_counted_as_failure(self):
        self.assertEqual(self.chains["C"]["completion"]["completion"], "提前结束")
        self.assertEqual(self.chains["D"]["completion"]["completion"], "未观察")
        self.assertEqual(self.chains["E"]["completion"]["completion"], "未观察")
        self.assertEqual(self.chains["A"]["completion"]["completion"], "可能完成")
        self.assertEqual(self.chains["B"]["completion"]["completion"], "可能完成")

    def test_broken_handover_is_detectable(self):
        # 构造步行时间不可能成立的断裂交接
        book = load(SAMPLE)
        book["stations"] = [
            {"ref": "x1", "group_choices": ["B"], "station": "讲堂",
             "in_at": "11:00", "out_at": "11:55", "known_seq": 1},
            {"ref": "x2", "group_choices": ["B"], "station": "实践室",
             "in_at": "11:56", "out_at": None, "known_seq": 2},
        ]
        chains = build_chains(book)
        handover = chains["B"]["handovers"][0]
        self.assertEqual(handover["status"], BROKEN)
        self.assertLess(handover["slack_min"], 0)
        self.assertEqual(chains["B"]["completion"]["completion"], "失败")

    def test_missing_visit_is_absence_not_zero_time(self):
        room = next(v for v in self.chains["E"]["visits"] if v["station"] == "实践室")
        self.assertEqual(room["arrival"], MISSING)
        self.assertIsNone(room["in_at"])


if __name__ == "__main__":
    unittest.main()
