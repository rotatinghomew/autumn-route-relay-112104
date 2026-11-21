"""资料装载与结构校验测试。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tempfile
import unittest

from yanxue.book import add_group, add_station_record, load, save

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "samples.json"


class SourceBookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = load(SAMPLE)

    def test_references(self):
        for detail, key, master, master_key in REFERENCES:
            with self.subTest(detail=detail, field=key):
                acceptable = {row[master_key] for row in self.book[master]}
                for row in self.book[detail]:
                    value = row[key]
                    if value is not None:
                        values = value if isinstance(value, list) else [value]
                        self.assertTrue(set(values) <= acceptable)

    def test_bad_row_width_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            malformed = Path(directory) / "bad.json"
            malformed.write_text(
                '{"format_version":1,"tables":{"groups":{"fields":["g"],"rows":[[1,2]]},'
                '"stations":{"fields":["ref"],"rows":[]},"services":{"fields":["version"],"rows":[]},'
                '"offers":{"fields":["slot"],"rows":[]},"notices":{"fields":["notice"],"rows":[]}}}',
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load(malformed)

    def test_unknown_state_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            book = load(SAMPLE)
            with self.assertRaises(ValueError):
                add_group(book, "Z", "2026-11-14", "v1", "东门", 2, 0, "迷之状态")

    def test_duplicate_group_rejected_and_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            book = load(SAMPLE)
            with self.assertRaises(ValueError):
                add_group(book, "A", "2026-11-14", "v1", "东门", 2, 0, "等待")
            add_group(book, "F", "2026-11-14", "v1", "北门", 3, 10, "等待")
            add_station_record(book, "q1", ["F"], "讲堂", "09:10", None, 1)
            target = Path(directory) / "work.json"
            save(book, target)
            reloaded = load(target)
            self.assertIn("F", {row["group"] for row in reloaded["groups"]})
            self.assertIn("q1", {row["ref"] for row in reloaded["stations"]})


REFERENCES = [
    ("stations", "group_choices", "groups", "group"),
    ("notices", "slot", "offers", "slot"),
    ("groups", "version", "services", "version"),
]
