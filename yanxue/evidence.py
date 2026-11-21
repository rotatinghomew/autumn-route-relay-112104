"""证据归属与全程联程重建。

原则（对应业务约束）：
- 只对时空上能成立且证据支持的联程作确定归属；
- 同时撞两团的凭证保持不确定，不复制成两次到达；
- 出站缺报但下一站证明已到达时，离开时刻给范围，不当缺席；
- 提前结束、等待改签、观察未满不算失败，与失败分开标注；
- 不做各站独立准点率相乘，全程机会只由联程证据推出。
"""
from __future__ import annotations

from collections import defaultdict

from .timeutil import hm, overlaps, parse_hm

CERTAIN = "确定"
AMBIGUOUS = "待定"
EXCLUDED = "排除"
ARRIVED = "已到达"
POSSIBLE = "可能到达"
MISSING = "缺报"
EARLY = "早于窗口"
LATE = "晚于窗口"
OK = "可行"
BROKEN = "断裂"
OPEN = "未观察"
FINISHED = "完结"
EARLY_END = "提前结束"
WAITING = "等待"
IMMATURE = "未成熟"

OPEN_STATES = {WAITING, IMMATURE}


def _service_map(index):
    """version -> station -> 服务窗口与步行时间（分钟）。"""
    mapping = defaultdict(dict)
    for row in index["services"]:
        mapping[row["version"]][row["station"]] = {
            "start": parse_hm(row["start"]),
            "end": parse_hm(row["end"]),
            "walk_min": row["walk_min"],
        }
    return dict(mapping)


def _spacetime_clash(rec, other):
    """同站且在场区间重叠即相撞；缺离开时刻按零时长处理。"""
    if rec["station"] != other["station"]:
        return False
    a_in, a_out = parse_hm(rec["in_at"]), parse_hm(rec["out_at"])
    b_in, b_out = parse_hm(other["in_at"]), parse_hm(other["out_at"])
    return overlaps(a_in, a_out or a_in, b_in, b_out or b_in)


def _attribute(records):
    """对每条凭证做候选团排除，返回 ref -> {团: 归属状态}。

    两条同站相撞的凭证，独占候选的团不可能同时出现在对方凭证上，
    因此从对方的候选集合中剔除；剩余 1 个候选即确定，多个即待定。
    """
    candidates = {rec["ref"]: set(rec["group_choices"]) for rec in records}
    for i, rec in enumerate(records):
        for other in records[i + 1 :]:
            if not _spacetime_clash(rec, other):
                continue
            rec_only = candidates[rec["ref"]] - candidates[other["ref"]]
            other_only = candidates[other["ref"]] - candidates[rec["ref"]]
            candidates[other["ref"]] -= rec_only
            candidates[rec["ref"]] -= other_only

    attributions = {}
    for rec in records:
        members = candidates[rec["ref"]]
        if len(members) == 1:
            status = CERTAIN
        elif len(members) > 1:
            status = AMBIGUOUS
        else:
            status = EXCLUDED
        attributions[rec["ref"]] = {group: status for group in members}
    return attributions


def build_chains(index):
    """按团重建全程联程，返回 group -> 链路结构。"""
    services = _service_map(index)
    attributions = _attribute(index["stations"])

    by_group = defaultdict(list)
    for rec in index["stations"]:
        for group, status in attributions[rec["ref"]].items():
            by_group[group].append((rec, status))

    chains = {}
    for grow in index["groups"]:
        group = grow["group"]
        version_services = services.get(grow["version"], {})
        ordered = sorted(version_services.items(), key=lambda kv: kv[1]["start"])
        group_records = by_group.get(group, [])

        visits = []
        for station, svc in ordered:
            here = [
                (rec, status)
                for rec, status in group_records
                if rec["station"] == station
            ]
            here.sort(key=lambda pair: (pair[0]["known_seq"], pair[0]["ref"]))
            visits.append(_visit(group, station, svc, here, ordered, index))

        handovers = [_handover(prev, nxt) for prev, nxt in zip(visits, visits[1:])]
        chains[group] = {
            "group": group,
            "day": grow["day"],
            "version": grow["version"],
            "origin": grow["origin"],
            "size": grow["size"],
            "rest_min": grow["rest_min"],
            "state": grow["state"],
            "visits": visits,
            "handovers": handovers,
            "completion": _completion(grow["state"], visits, handovers),
        }
    return chains


def _visit(group, station, svc, here, ordered, index):
    """构造单个站点的结论，含缺报离开时刻的范围推断。"""
    evidence = []
    for rec, status in here:
        evidence.append(
            {
                "ref": rec["ref"],
                "in_at": rec["in_at"],
                "out_at": rec["out_at"],
                "known_seq": rec["known_seq"],
                "attribution": status,
                "shared_with": [g for g in rec["group_choices"] if g != group],
            }
        )

    certain = [e for e in evidence if e["attribution"] == CERTAIN]
    ambiguous = [e for e in evidence if e["attribution"] == AMBIGUOUS]
    chosen = certain[0] if certain else (ambiguous[0] if ambiguous else None)

    visit = {
        "station": station,
        "window_start": hm(svc["start"]),
        "window_end": hm(svc["end"]),
        "walk_min": svc["walk_min"],
        "evidence": evidence,
        "attribution": MISSING if chosen is None else chosen["attribution"],
        "arrival": MISSING,
        "window_state": None,
        "in_at": None,
        "out_at": None,
        "out_range": None,
        "out_range_basis": None,
    }
    if chosen is None:
        return visit

    visit["arrival"] = ARRIVED if chosen["attribution"] == CERTAIN else POSSIBLE
    visit["in_at"] = chosen["in_at"]
    visit["out_at"] = chosen["out_at"]

    in_min = parse_hm(chosen["in_at"])
    if in_min < svc["start"]:
        visit["window_state"] = EARLY
    elif in_min > svc["end"]:
        visit["window_state"] = LATE
    else:
        visit["window_state"] = OK

    # 出站缺报：下一站凭证能证明本团已到达时，离开时刻给范围而非缺席。
    if chosen["out_at"] is None:
        station_names = [name for name, _ in ordered]
        idx = station_names.index(station)
        if idx + 1 < len(ordered):
            next_station = station_names[idx + 1]
            proof, proof_basis = next_station_proof(index, group, next_station)
            if proof is not None:
                lower = in_min
                upper = parse_hm(proof["in_at"]) - svc["walk_min"]
                visit["out_range"] = [hm(lower), hm(max(lower, upper))]
                visit["out_range_basis"] = proof_basis
    return visit


def next_station_proof(index, group, station):
    """下一站能证明本团已到达的最早凭证。

    确定归属优先；只有待定凭证时退而求其次并标明“待定凭证”，
    范围结论随证据保持不确定。无本团候选时返回 (None, None)。
    """
    proofs = [
        rec
        for rec in index["stations"]
        if rec["station"] == station and group in rec["group_choices"]
    ]
    if not proofs:
        return None, None
    certain = [rec for rec in proofs if len(rec["group_choices"]) == 1]
    if certain:
        rec = sorted(certain, key=lambda r: (parse_hm(r["in_at"]), r["ref"]))[0]
        return rec, "下一站确定凭证"
    rec = sorted(proofs, key=lambda r: (parse_hm(r["in_at"]), r["ref"]))[0]
    return rec, "下一站待定凭证"


def _handover(prev, nxt):
    """两站交接：以步行最短时间检验时空可行性。"""
    result = {
        "from": prev["station"],
        "to": nxt["station"],
        "walk_min": nxt["walk_min"],
        "status": OPEN,
        "reason": None,
        "slack_min": None,
        "depart_basis": None,
        "evidence_uncertain": False,
    }
    if prev["arrival"] == MISSING or nxt["arrival"] == MISSING:
        result["reason"] = "前段或本段无到达凭证"
        return result

    if prev["out_at"] is not None:
        depart = parse_hm(prev["out_at"])
        result["depart_basis"] = "精确"
    elif prev["out_range"] is not None:
        # 范围下界是最早可能离开时刻：下界都赶不到才构成断裂，
        # 这样保守判断不会把可成立的联程误判为失败。
        depart = parse_hm(prev["out_range"][0])
        result["depart_basis"] = "缺报范围下界"
    else:
        result["reason"] = "前段离开时刻未观测且无后续证明"
        return result

    arrive = parse_hm(nxt["in_at"])
    slack = arrive - depart - nxt["walk_min"]
    result["slack_min"] = slack
    result["evidence_uncertain"] = (
        prev["attribution"] == AMBIGUOUS or nxt["attribution"] == AMBIGUOUS
    )
    if slack < 0:
        result["status"] = BROKEN
        result["reason"] = f"步行至少 {nxt['walk_min']} 分钟，时间差不足 {-slack} 分钟"
    else:
        result["status"] = OK
        result["reason"] = "时间差满足最短步行"
    return result


def _completion(state, visits, handovers):
    """全程结论：失败与未观察严格分开，绝不把未成熟团算失败。"""
    arrivals = [v["arrival"] for v in visits]
    if arrivals and all(a == ARRIVED for a in arrivals):
        overall = ARRIVED
    elif any(a in (ARRIVED, POSSIBLE) for a in arrivals):
        overall = POSSIBLE
    else:
        overall = MISSING

    broken = [h for h in handovers if h["status"] == BROKEN]
    open_handover = [h for h in handovers if h["status"] == OPEN]

    if broken:
        completion = "失败"
    elif state in OPEN_STATES:
        completion = "未观察"
    elif state == EARLY_END:
        completion = "提前结束"
    elif overall == ARRIVED and not open_handover:
        completion = "全程完成"
    elif overall == MISSING:
        completion = "未观察"
    else:
        completion = "可能完成"
    return {
        "completion": completion,
        "arrival_basis": overall,
        "broken_handovers": [f"{h['from']}->{h['to']}" for h in broken],
        "open_handovers": [f"{h['from']}->{h['to']}" for h in open_handover],
        "state": state,
    }
