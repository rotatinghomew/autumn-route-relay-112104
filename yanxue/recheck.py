"""补证复检：景点补回回执后重新检验结论，并说明可调团剩余空间。

复检只对比“新证据是否改变上次结论”，不重写历史签发；
结论被改变的团才进入重新检验名单，并重新评估其在台账下的可调整选择。
"""
from __future__ import annotations

from .evidence import build_chains
from .planning import audit_group, readiness


def recheck(index_before, index_after, ledger):
    """对比补证前后的链路结论，逐团给出变化与剩余可调空间。"""
    before = build_chains(index_before)
    after = build_chains(index_after)

    changed, unchanged = [], []
    for group, new_chain in after.items():
        old_chain = before.get(group)
        if old_chain is None:
            changed.append({"group": group, "change": "新团期", "from": None,
                            "to": _signature(new_chain)})
            continue
        old_sig, new_sig = _signature(old_chain), _signature(new_chain)
        if old_sig != new_sig:
            changed.append(
                {
                    "group": group,
                    "change": "结论改变",
                    "from": old_sig,
                    "to": new_sig,
                }
            )
        else:
            unchanged.append(group)

    adjustable = []
    for item in changed:
        group = item["group"]
        if group not in after:
            continue
        audit = audit_group(index_after, after, ledger, group)
        ready = readiness(after[group])
        open_options = [
            opt for opt in audit["options"]
            if opt.get("feasible") is True and opt["remaining_conservative"] > 0
        ]
        adjustable.append(
            {
                "group": group,
                "change": item["change"],
                "readiness": ready,
                "open_options": open_options,
                "blocked_options": [
                    {
                        "slot": opt["slot"],
                        "protocol": opt["protocol"],
                        "feasible": opt["feasible"],
                        "reason": opt.get("reason"),
                    }
                    for opt in audit["options"]
                    if opt["protocol"] != "current"
                    and (opt.get("feasible") is not True or opt["remaining_conservative"] <= 0)
                ],
                "audit": audit,
            }
        )

    return {
        "changed": changed,
        "unchanged": unchanged,
        "recheck_groups": adjustable,
        "ledger_protected": "历史签发与已确认替代不随复检改写，只追加新签发",
    }


def _signature(chain):
    """结论指纹：站点归属/时刻/交接状态/全程结论。"""
    return {
        "completion": chain["completion"]["completion"],
        "visits": [
            {
                "station": v["station"],
                "arrival": v["arrival"],
                "attribution": v["attribution"],
                "in_at": v["in_at"],
                "out_at": v["out_at"],
                "out_range": v["out_range"],
            }
            for v in chain["visits"]
        ],
        "handovers": [
            {"handover": f"{h['from']}->{h['to']}", "status": h["status"],
             "slack_min": h["slack_min"]}
            for h in chain["handovers"]
        ],
    }
