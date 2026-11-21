"""签发台账：承诺、换场协议与同一班次余位对账。

台账独立于只读样册保存。三类占位：
- signed：原签发承诺；
- accepted_alternate：团长已确认的替代安排（原承诺转 superseded）；
- pending_change：仍待团长确认的改签，保守口径先占余位。
无法安置的原承诺不删除，保留 active 并在试算/签发时列为 conflict。
"""
from __future__ import annotations

import json
from pathlib import Path

SIGNED = "signed"
ACCEPTED = "accepted_alternate"
PENDING = "pending_change"
ACTIVE = "active"
SUPERSEDED = "superseded"
CONFLICT = "conflict"


def init_ledger(index):
    """从 notices 初始化台账：原承诺、已接受替代、待确认改签各自归位。"""
    ledger = {"format_version": 1, "commitments": [], "issues": []}
    for notice in index["notices"]:
        seq = notice["seq"]
        original = {
            "commitment_id": f"C-{notice['notice']}-原",
            "group": notice["group"],
            "slot": notice["slot"],
            "size": notice["size"],
            "kind": SIGNED,
            "notice": notice["notice"],
            "issued_seq": seq,
            "status": ACTIVE,
        }
        ledger["commitments"].append(original)
        if notice["alternate"] is not None:
            if notice["accepted"] == notice["alternate"]:
                original["status"] = SUPERSEDED
                ledger["commitments"].append(
                    {
                        "commitment_id": f"C-{notice['notice']}-替",
                        "group": notice["group"],
                        "slot": notice["alternate"],
                        "size": notice["size"],
                        "kind": ACCEPTED,
                        "notice": notice["notice"],
                        "issued_seq": seq,
                        "status": ACTIVE,
                    }
                )
            else:
                # 协议已发到团长手上但尚未确认：保守占位，不改原承诺
                ledger["commitments"].append(
                    {
                        "commitment_id": f"C-{notice['notice']}-待",
                        "group": notice["group"],
                        "slot": notice["alternate"],
                        "size": notice["size"],
                        "kind": PENDING,
                        "notice": notice["notice"],
                        "issued_seq": seq,
                        "status": ACTIVE,
                    }
                )
    return ledger


def load_ledger(path):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"台账不存在，请先初始化：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def save_ledger(ledger, path):
    Path(path).write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def active_commitments(ledger, group=None, slot=None):
    rows = [c for c in ledger["commitments"] if c["status"] == ACTIVE]
    if group is not None:
        rows = [c for c in rows if c["group"] == group]
    if slot is not None:
        rows = [c for c in rows if c["slot"] == slot]
    return rows


def _offer_index(index):
    return {row["slot"]: row for row in index["offers"]}


def capacity_view(index, ledger):
    """逐班次对账：原签发、已接受替代、待确认改签与剩余可承接人数。"""
    offers = _offer_index(index)
    view = []
    for slot, offer in sorted(offers.items()):
        rows = active_commitments(ledger, slot=slot)
        signed = [c for c in rows if c["kind"] == SIGNED]
        accepted = [c for c in rows if c["kind"] == ACCEPTED]
        pending = [c for c in rows if c["kind"] == PENDING]
        committed = sum(c["size"] for c in signed + accepted)
        held = sum(c["size"] for c in pending)
        remaining_conservative = offer["capacity"] - committed - held
        remaining_if_rejected = offer["capacity"] - committed
        view.append(
            {
                "slot": slot,
                "option": offer["option"],
                "day": offer["day"],
                "time": offer["time"],
                "capacity": offer["capacity"],
                "signed": [_brief(c) for c in signed],
                "accepted_alternates": [_brief(c) for c in accepted],
                "pending_changes": [_brief(c) for c in pending],
                "committed_seats": committed,
                "pending_held_seats": held,
                "remaining_conservative": remaining_conservative,
                "remaining_if_pending_rejected": remaining_if_rejected,
                "overbooked": remaining_conservative < 0,
            }
        )
    return view


def _brief(commitment):
    return {
        "commitment_id": commitment["commitment_id"],
        "group": commitment["group"],
        "size": commitment["size"],
        "notice": commitment["notice"],
    }


def next_issue_seq(ledger):
    if not ledger["issues"]:
        return 1
    return max(row["issued_seq"] for row in ledger["issues"]) + 1


def next_commitment_seq(ledger):
    return len(ledger["commitments"]) + 1
