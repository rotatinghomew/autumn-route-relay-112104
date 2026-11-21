"""备选接驳时刻试算与签发。

试算规则：
- 同一批可比出发团（同日）统一评估，共享补救场次余位只占用一次；
- 换早班同时检验最短步行与团的照护间隔 rest_min；
- 已发到团长手上的时间，只能按其确认过的换场协议变更；
  待确认改签不得当作可执行，无法安置的原承诺继续占位并列为冲突；
- 未知时间或待定归属足以反转推荐时，试算只作参考、不得签发。
"""
from __future__ import annotations

from .evidence import AMBIGUOUS, MISSING
from .ledger import (
    ACCEPTED,
    ACTIVE,
    CONFLICT,
    PENDING,
    SIGNED,
    SUPERSEDED,
    active_commitments,
    capacity_view,
    next_commitment_seq,
    next_issue_seq,
)
from .timeutil import hm, parse_hm


def readiness(chain):
    """团在返程站点的最早可登车时刻及其证据质量。"""
    boarding = chain["visits"][-1]
    result = {
        "group": chain["group"],
        "boarding_station": boarding["station"],
        "walk_min": boarding["walk_min"],
        "known": False,
        "earliest_board": None,
        "precise_depart": False,
        "evidence_uncertain": False,
        "reasons": [],
    }
    if len(chain["visits"]) < 2:
        result["reasons"].append("行程少于两个站点，无法推算登车时刻")
        return result
    prior = chain["visits"][-2]
    if prior["arrival"] == MISSING:
        result["reasons"].append(f"{prior['station']} 无到达凭证")
        return result
    if prior["out_at"] is not None:
        depart = parse_hm(prior["out_at"])
        result["precise_depart"] = True
        depart_basis = "精确离开"
    elif prior["out_range"] is not None:
        # 范围下界=最早可能离开，用于“能否赶上”的保守判断
        depart = parse_hm(prior["out_range"][0])
        depart_basis = "离开范围下界"
    else:
        result["reasons"].append(f"{prior['station']} 离开时刻未观测且无后续证明")
        return result

    in_min = parse_hm(prior["in_at"])
    walk_ready = depart + boarding["walk_min"]
    # 照护间隔从可登车前的最后一段活动结束（实践室离开）起算
    rest_ready = depart + chain["rest_min"]
    earliest = max(walk_ready, rest_ready)
    result.update(
        {
            "known": True,
            "earliest_board": hm(earliest),
            "earliest_board_min": earliest,
            "depart_basis": depart_basis,
            "walk_ready": hm(walk_ready),
            "rest_ready": hm(rest_ready),
            "evidence_uncertain": prior["attribution"] == AMBIGUOUS,
        }
    )
    return result


def _notice_index(index):
    """group -> 与本团相关的通知列表。"""
    mapping = {}
    for notice in index["notices"]:
        mapping.setdefault(notice["group"], []).append(notice)
    return mapping


def _protocol_for(index, group, current_slots, target_slot):
    """返回目标场次对应的换场协议状态。

    通知的 slot 是原承诺场次、alternate 是拟改入场次；
    目标场次本身已是在效承诺（如待确认占位）不构成换场授权。
    """
    for notice in _notice_index(index).get(group, []):
        if notice["alternate"] != target_slot or notice["slot"] not in current_slots:
            continue
        if notice["accepted"] == target_slot:
            return "accepted", notice
        return "pending", notice
    return None, None


def evaluate_scenario(index, chains, ledger, scenario):
    """评估一套接驳方案。scenario: {scenario, groups, assignments}。"""
    assignments = scenario.get("assignments", {})
    cohort = scenario["groups"]
    offers = {row["slot"]: row for row in index["offers"]}
    chain_by_group = {c["group"]: c for c in chains.values()}
    readies = {g: readiness(chain_by_group[g]) for g in cohort}

    group_results = []
    slot_demand = {}
    conflicts = []

    for group in cohort:
        chain = chain_by_group[group]
        ready = readies[group]
        current = [c["slot"] for c in active_commitments(ledger, group=group)]
        signed_slots = [
            c["slot"] for c in active_commitments(ledger, group=group)
            if c["kind"] in (SIGNED, ACCEPTED)
        ]
        target = assignments.get(group) or (current[0] if current else None)
        result = {
            "group": group,
            "current_slots": current,
            "proposed": target,
            "changed": bool(target and target not in signed_slots),
            "feasible": False,
            "blocked_reasons": [],
            "checks": [],
            "evidence_uncertain": ready["evidence_uncertain"],
        }

        if target is None:
            result["blocked_reasons"].append("无方案且无在效承诺")
            conflicts.append({"group": group, "reason": result["blocked_reasons"][-1]})
            group_results.append(result)
            continue

        offer = offers.get(target)
        if offer is None:
            result["blocked_reasons"].append(f"场次 {target} 不存在")
        elif offer["day"] != chain["day"]:
            result["blocked_reasons"].append("另日场次不能承接本日团")
        elif group not in offer["eligible_groups"]:
            result["blocked_reasons"].append(f"团 {group} 不在 {target} 的可接范围")

        if ready["known"] and offer is not None and offer["day"] == chain["day"]:
            offer_min = parse_hm(offer["time"])
            slack = offer_min - ready["earliest_board_min"]
            walk_slack = offer_min - parse_hm(ready["walk_ready"])
            rest_slack = offer_min - parse_hm(ready["rest_ready"])
            result["checks"].append(
                {
                    "earliest_board": ready["earliest_board"],
                    "offer_time": offer["time"],
                    "slack_min": slack,
                    "walk_slack_min": walk_slack,
                    "rest_slack_min": rest_slack,
                    "depart_basis": ready["depart_basis"],
                }
            )
            if walk_slack < 0:
                result["blocked_reasons"].append(
                    f"步行至少 {ready['walk_min']} 分钟，赶不上 {offer['time']}（差 {-walk_slack} 分钟）"
                )
            if rest_slack < 0:
                result["blocked_reasons"].append(
                    f"照护间隔 {chain['rest_min']} 分钟无法满足（差 {-rest_slack} 分钟）"
                )
        elif not ready["known"]:
            result["blocked_reasons"].extend(f"证据不足：{r}" for r in ready["reasons"])

        # 换场协议检查：物理可行后仍须有团长确认过的协议
        if result["changed"]:
            status, notice = _protocol_for(index, group, current, target)
            if status is None:
                result["blocked_reasons"].append("无团长确认过的换场协议，不能变更已签发时间")
                result["protocol"] = "missing"
            elif status == "pending":
                result["blocked_reasons"].append(
                    f"换场协议 {notice['notice']} 仍待团长确认，原承诺继续占位"
                )
                result["protocol"] = "pending"
                conflicts.append(
                    {
                        "group": group,
                        "slot": current[0] if current else None,
                        "reason": f"待确认改签 {notice['notice']}，无法安置为 {target}",
                    }
                )
            else:
                result["protocol"] = "accepted"
                result["checks"].append({"protocol": notice["notice"], "status": "accepted"})

        result["feasible"] = not result["blocked_reasons"]
        if result["feasible"]:
            slot_demand.setdefault(target, []).append(group)
        elif current:
            # 方案不可行：原承诺不删，继续占原班次
            for slot in current:
                slot_demand.setdefault(slot, []).append(group)
        group_results.append(result)

    # 余位：试算团外的既存有效承诺照常占位；共享场次余位只算一次
    usage = {}
    cohort_set = set(cohort)
    for slot, offer in offers.items():
        outsiders = [
            c["group"]
            for c in active_commitments(ledger, slot=slot)
            if c["group"] not in cohort_set
        ]
        users = sorted(set(slot_demand.get(slot, []) + outsiders))
        sizes = {g: chain_by_group[g]["size"] for g in cohort}
        for c in active_commitments(ledger, slot=slot):
            if c["group"] not in cohort_set:
                sizes[c["group"]] = c["size"]
        demand = sum(sizes[g] for g in users)
        usage[slot] = {
            "day": offer["day"],
            "time": offer["time"],
            "capacity": offer["capacity"],
            "users": users,
            "demand_seats": demand,
            "remaining": offer["capacity"] - demand,
            "overbooked": demand > offer["capacity"],
        }
        if usage[slot]["overbooked"]:
            conflicts.append(
                {
                    "slot": slot,
                    "reason": f"需求 {demand} 人超过容量 {offer['capacity']} 人",
                    "users": users,
                }
            )

    hard_blocked = any(not r["feasible"] for r in group_results)
    evidence_gap = any(
        r["evidence_uncertain"] or any("证据不足" in x for x in r["blocked_reasons"])
        for r in group_results
    )
    return {
        "scenario": scenario.get("scenario"),
        "groups": cohort,
        "group_results": group_results,
        "slot_usage": usage,
        "conflicts": conflicts,
        "evidence_gap": evidence_gap,
        "executable": not hard_blocked and not conflicts and not evidence_gap,
        "recommendation_reversible": evidence_gap,
        "notice": "存在证据缺口时结论可能反转，试算不得作为可执行承诺"
        if evidence_gap
        else None,
    }


def issue_scenario(index, chains, ledger, result, scenario):
    """把可执行试算签发到台账，分段承接；不可执行则只登记冲突。"""
    seq = next_issue_seq(ledger)
    issue = {
        "issued_seq": seq,
        "scenario": result["scenario"],
        "actions": [],
        "conflicts": [],
    }
    if not result["executable"]:
        issue["conflicts"] = result["conflicts"]
        issue["status"] = "rejected"
        ledger["issues"].append(issue)
        return issue

    offers = {row["slot"]: row for row in index["offers"]}
    for gr in result["group_results"]:
        group = gr["group"]
        target = gr["proposed"]
        existing = active_commitments(ledger, group=group)
        if not existing:
            ledger["commitments"].append(
                {
                    "commitment_id": f"C-{next_commitment_seq(ledger)}",
                    "group": group,
                    "slot": target,
                    "size": next(c["size"] for c in index["groups"] if c["group"] == group),
                    "kind": SIGNED,
                    "notice": None,
                    "issued_seq": seq,
                    "status": ACTIVE,
                }
            )
            issue["actions"].append({"group": group, "slot": target, "action": "new_signed"})
            continue

        for commitment in existing:
            if commitment["slot"] == target:
                issue["actions"].append(
                    {"group": group, "slot": target, "action": "retain",
                     "commitment_id": commitment["commitment_id"]}
                )
            elif commitment["kind"] == SIGNED:
                status, notice = _protocol_for(
                    index, group, [c["slot"] for c in existing], target
                )
                if status == "accepted":
                    commitment["status"] = SUPERSEDED
                    issue["actions"].append(
                        {"group": group, "slot": target, "action": "change_accepted",
                         "notice": notice["notice"]}
                    )
                else:
                    commitment["status"] = CONFLICT
                    issue["conflicts"].append(
                        {"group": group, "slot": commitment["slot"],
                         "reason": "无已确认换场协议，原承诺保留为冲突"}
                    )
    issue["status"] = "issued" if not issue["conflicts"] else "partial"
    ledger["issues"].append(issue)
    return issue


def audit_group(index, chains, ledger, group):
    """逐团查清：签发依据、现有选择、不能换的原因。"""
    chain = next(c for c in chains.values() if c["group"] == group)
    ready = readiness(chain)
    capacities = {row["slot"]: row for row in capacity_view(index, ledger)}
    commitments = active_commitments(ledger, group=group)

    options = []
    for offer in index["offers"]:
        if offer["day"] != chain["day"] or group not in offer["eligible_groups"]:
            continue
        slot = offer["slot"]
        item = {
            "slot": slot,
            "option": offer["option"],
            "time": offer["time"],
            "remaining_conservative": capacities[slot]["remaining_conservative"],
        }
        if not ready["known"]:
            item["feasible"] = None
            item["reason"] = "；".join(ready["reasons"])
        else:
            slack = parse_hm(offer["time"]) - ready["earliest_board_min"]
            item["feasible"] = slack >= 0
            item["slack_min"] = slack
        current_slots = [c["slot"] for c in commitments]
        if slot not in current_slots:
            status, notice = _protocol_for(index, group, current_slots, slot)
            item["protocol"] = status or "missing"
            if notice is not None:
                item["notice"] = notice["notice"]
        else:
            item["protocol"] = "current"
        options.append(item)

    return {
        "group": group,
        "state": chain["state"],
        "completion": chain["completion"],
        "readiness": ready,
        "commitments": commitments,
        "issue_basis": [
            {"issue_seq": c["issued_seq"], "notice": c["notice"], "kind": c["kind"],
             "slot": c["slot"], "status": c["status"]}
            for c in ledger["commitments"] if c["group"] == group
        ],
        "options": options,
    }
