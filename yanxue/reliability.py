"""全程完成机会与交接损失报告。

口径：
- 完成机会按联程证据计数，给确定数/可能数形成的区间，绝不相乘独立准点率；
- 等待、未成熟、提前结束的团单列，不进失败计数；
- 证据共享导致无法区分的团之间，比较列为 blocked，不作结论。
"""
from __future__ import annotations

from collections import defaultdict

from .evidence import (
    AMBIGUOUS,
    ARRIVED,
    BROKEN,
    MISSING,
    OPEN,
    POSSIBLE,
)

FINISHED_LIKE = {"全程完成", "可能完成", "失败", "提前结束"}


def reliability_report(chains, origin=None, rest_min=None, version=None):
    """按出发站/同行照护需求/行程版本过滤后出报告。"""
    selected = [
        chain
        for chain in chains.values()
        if (origin is None or chain["origin"] == origin)
        and (rest_min is None or chain["rest_min"] >= rest_min)
        and (version is None or chain["version"] == version)
    ]
    cohorts = defaultdict(list)
    for chain in selected:
        cohorts[(chain["day"], chain["version"])].append(chain)

    cohort_reports = [
        _cohort(day, ver, members)
        for (day, ver), members in sorted(cohorts.items())
    ]
    return {
        "filters": {"origin": origin, "rest_min": rest_min, "version": version},
        "group_count": len(selected),
        "cohorts": cohort_reports,
        "blocked_comparisons": _blocked_comparisons(selected),
        "method": "全程机会由联程凭证计数得到区间，不使用各站独立准点率相乘",
    }


def _cohort(day, version, members):
    completed = [c["group"] for c in members if c["completion"]["completion"] == "全程完成"]
    possible = [
        c["group"]
        for c in members
        if c["completion"]["completion"] in ("全程完成", "可能完成")
    ]
    failed = [c["group"] for c in members if c["completion"]["completion"] == "失败"]
    early_ended = [c["group"] for c in members if c["completion"]["completion"] == "提前结束"]
    open_groups = [c["group"] for c in members if c["completion"]["completion"] == "未观察"]
    total = len(members)

    handover_losses = []
    for chain in members:
        for handover in chain["handovers"]:
            if handover["status"] == BROKEN:
                handover_losses.append(
                    {
                        "group": chain["group"],
                        "handover": f"{handover['from']}->{handover['to']}",
                        "slack_min": handover["slack_min"],
                        "reason": handover["reason"],
                        "rest_min": chain["rest_min"],
                    }
                )

    def rate(count):
        return round(count / total, 4) if total else None

    return {
        "day": day,
        "version": version,
        "groups": [c["group"] for c in members],
        "completion": {
            "certain_completed": sorted(completed),
            "possible_completed": sorted(possible),
            "rate_range": [rate(len(completed)), rate(len(possible))],
            "count_range": [len(completed), len(possible)],
        },
        "losses": {
            "failed": sorted(failed),
            "early_ended": sorted(early_ended),
            "handover_breaks": handover_losses,
        },
        "unobserved": sorted(open_groups),
    }


def _blocked_comparisons(members):
    """列出证据不足而不能作的比较。"""
    blocked = []

    # 1. 共享同一条待定凭证的两个团，无法在该站区分，不能比准点。
    shared_pairs = defaultdict(set)
    for chain in members:
        for visit in chain["visits"]:
            for ev in visit["evidence"]:
                if ev["attribution"] == AMBIGUOUS:
                    for other in ev["shared_with"]:
                        pair = tuple(sorted((chain["group"], other)))
                        shared_pairs[pair].add(visit["station"])
    for (a, b), stations in sorted(shared_pairs.items()):
        blocked.append(
            {
                "type": "共享待定凭证",
                "groups": [a, b],
                "scope": f"站点 {sorted(stations)} 的到达归属",
                "reason": "同一时空凭证可能属于任一团，不能复制成两次到达后再比较",
            }
        )

    # 2. 未观察结局的团不能与已完结团比完成率。
    open_groups = [c["group"] for c in members if c["completion"]["completion"] == "未观察"]
    closed = [
        c["group"]
        for c in members
        if c["completion"]["completion"] in FINISHED_LIKE and c["completion"]["completion"] != "未观察"
    ]
    for og in sorted(open_groups):
        blocked.append(
            {
                "type": "结局未观察",
                "groups": [og] + sorted(g for g in closed if g != og),
                "scope": "全程完成率比较",
                "reason": "等待改签或观察未满，既不能算失败也不能算完成",
            }
        )

    # 3. 关键时间缺报且无范围可推的交接，不能判断谁先谁后。
    for chain in members:
        for handover in chain["handovers"]:
            if handover["status"] == OPEN:
                blocked.append(
                    {
                        "type": "交接证据不足",
                        "groups": [chain["group"]],
                        "scope": f"{handover['from']}->{handover['to']}",
                        "reason": handover["reason"],
                    }
                )
    return blocked


def chain_detail(chain):
    """单团详情：逐站证据、离开范围、逐段交接与最终结论。"""
    visits = []
    for visit in chain["visits"]:
        visits.append(
            {
                "station": visit["station"],
                "window": [visit["window_start"], visit["window_end"]],
                "arrival": visit["arrival"],
                "window_state": visit["window_state"],
                "attribution": visit["attribution"],
                "in_at": visit["in_at"],
                "out_at": visit["out_at"],
                "out_range": visit["out_range"],
                "out_range_basis": visit["out_range_basis"],
                "evidence": visit["evidence"],
            }
        )
    return {
        "group": chain["group"],
        "day": chain["day"],
        "version": chain["version"],
        "origin": chain["origin"],
        "size": chain["size"],
        "rest_min": chain["rest_min"],
        "state": chain["state"],
        "visits": visits,
        "handovers": chain["handovers"],
        "completion": chain["completion"],
    }
