"""资料交换簿：装载、结构校验、保存与新团期录入。

交换格式与 data/samples.json 一致：tables -> 表名 -> fields/rows/meaning。
录入新团期只写入工作簿副本，原始样册保持只读。
"""
from __future__ import annotations

import json
from pathlib import Path

from .timeutil import parse_hm

GROUP_STATES = {"完结", "提前结束", "等待", "未成熟"}
STATION_FIELDS = ["ref", "group_choices", "station", "in_at", "out_at", "known_seq"]
GROUP_FIELDS = ["group", "day", "version", "origin", "size", "rest_min", "state"]


def load(path):
    """装载并做表头/行宽/枚举/引用校验，返回按表名索引的记录列表。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "format_version" not in data or "tables" not in data:
        raise ValueError("缺少 format_version 或 tables")
    index = {}
    for name, table in data["tables"].items():
        fields = table["fields"]
        if not fields or len(fields) != len(set(fields)):
            raise ValueError(f"字段不匹配：{name}")
        if any(len(row) != len(fields) for row in table["rows"]):
            raise ValueError(f"字段不匹配：{name}")
        index[name] = [dict(zip(fields, row)) for row in table["rows"]]
    _validate(index)
    return index


def _validate(index):
    required = {"groups", "stations", "services", "offers", "notices"}
    missing = required - set(index)
    if missing:
        raise ValueError(f"缺少表：{sorted(missing)}")

    groups = {row["group"] for row in index["groups"]}
    if len(groups) != len(index["groups"]):
        raise ValueError("团号重复")
    versions = {row["version"] for row in index["groups"]}
    stations_named = {row["station"] for row in index["stations"]}
    slots = {row["slot"] for row in index["offers"]}

    for row in index["groups"]:
        if row["state"] not in GROUP_STATES:
            raise ValueError(f"未知团状态：{row['state']}")
        if not isinstance(row["size"], int) or row["size"] <= 0:
            raise ValueError(f"团人数须为正整数：{row['group']}")
        if not isinstance(row["rest_min"], int) or row["rest_min"] < 0:
            raise ValueError(f"照护间隔须为非负整数：{row['group']}")
        if row["version"] not in {s["version"] for s in index["services"]}:
            raise ValueError(f"行程版本无服务时刻：{row['version']}")

    for row in index["stations"]:
        if not row["group_choices"]:
            raise ValueError(f"凭证 {row['ref']} 缺少候选团")
        if not set(row["group_choices"]) <= groups:
            raise ValueError(f"凭证 {row['ref']} 引用了未知团")
        parse_hm(row["in_at"])
        parse_hm(row["out_at"])
        if row["out_at"] is not None and parse_hm(row["out_at"]) < parse_hm(row["in_at"]):
            raise ValueError(f"凭证 {row['ref']} 离开早于到达")
        if not isinstance(row["known_seq"], int):
            raise ValueError(f"凭证 {row['ref']} known_seq 须为整数")

    service_keys = {(s["version"], s["station"]) for s in index["services"]}
    for version in versions:
        if not any(s[0] == version for s in service_keys):
            raise ValueError(f"版本 {version} 无服务记录")
    for station in stations_named:
        if not any(key[1] == station for key in service_keys):
            raise ValueError(f"站点无服务时刻：{station}")
    for row in index["services"]:
        if parse_hm(row["end"]) < parse_hm(row["start"]):
            raise ValueError(f"服务窗口倒挂：{row['version']} {row['station']}")
        if not isinstance(row["walk_min"], int) or row["walk_min"] < 0:
            raise ValueError("walk_min 须为非负整数")

    for row in index["offers"]:
        parse_hm(row["time"])
        if not isinstance(row["capacity"], int) or row["capacity"] <= 0:
            raise ValueError(f"场次容量须为正整数：{row['slot']}")
        if not set(row["eligible_groups"]) <= groups:
            raise ValueError(f"场次 {row['slot']} 引用了未知团")

    for row in index["notices"]:
        if row["group"] not in groups:
            raise ValueError(f"通知 {row['notice']} 引用了未知团")
        if row["slot"] not in slots:
            raise ValueError(f"通知 {row['notice']} 引用了未知场次")
        if row["alternate"] is not None and row["alternate"] not in slots:
            raise ValueError(f"通知 {row['notice']} 引用了未知替代场次")
        if row["accepted"] is not None and row["accepted"] != row["alternate"]:
            raise ValueError(f"通知 {row['notice']} 确认值与替代场次不一致")


def save(index, path, format_version=1):
    """按交换格式写回；字段顺序沿用标准列序。"""
    field_order = {
        "groups": GROUP_FIELDS,
        "stations": STATION_FIELDS,
        "services": ["version", "station", "start", "end", "walk_min"],
        "offers": ["option", "slot", "day", "time", "capacity", "eligible_groups"],
        "notices": ["notice", "group", "slot", "size", "alternate", "accepted", "seq"],
    }
    tables = {}
    for name, fields in field_order.items():
        if name not in index:
            continue
        rows = [[row.get(field) for field in fields] for row in index[name]]
        tables[name] = {"fields": fields, "rows": rows}
    payload = {"format_version": format_version, "tables": tables}
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def add_group(index, group, day, version, origin, size, rest_min, state):
    """向工作簿追加一个新团期；团号冲突时拒绝。"""
    if any(row["group"] == group for row in index["groups"]):
        raise ValueError(f"团号已存在：{group}")
    index["groups"].append(
        {
            "group": group,
            "day": day,
            "version": version,
            "origin": origin,
            "size": size,
            "rest_min": rest_min,
            "state": state,
        }
    )
    _validate(index)


def add_station_record(index, ref, group_choices, station, in_at, out_at, known_seq):
    """追加一条分站接待凭证；引用与时刻由 _validate 统一把关。"""
    if any(row["ref"] == ref for row in index["stations"]):
        raise ValueError(f"凭证号已存在：{ref}")
    index["stations"].append(
        {
            "ref": ref,
            "group_choices": list(group_choices),
            "station": station,
            "in_at": in_at,
            "out_at": out_at,
            "known_seq": known_seq,
        }
    )
    _validate(index)
