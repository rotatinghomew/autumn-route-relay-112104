"""研学联程调度命令行入口。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from . import book as book_mod  # noqa: E402
from . import ledger as ledger_mod  # noqa: E402
from .evidence import build_chains  # noqa: E402
from .planning import audit_group, evaluate_scenario, issue_scenario  # noqa: E402
from .recheck import recheck  # noqa: E402
from .reliability import chain_detail, reliability_report  # noqa: E402


def _print(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _load(path):
    return book_mod.load(Path(path))


def _ledger_or_die(path):
    try:
        return ledger_mod.load_ledger(Path(path))
    except FileNotFoundError as exc:
        raise SystemExit(str(exc))


def cmd_tables(args):
    _print({name: len(rows) for name, rows in _load(args.path).items()})


def cmd_report(args):
    index = _load(args.path)
    chains = build_chains(index)
    _print(
        reliability_report(
            chains,
            origin=args.origin,
            rest_min=args.rest_min,
            version=args.version,
        )
    )


def cmd_chain(args):
    index = _load(args.path)
    chains = build_chains(index)
    if args.group not in chains:
        raise SystemExit(f"未知团：{args.group}")
    _print(chain_detail(chains[args.group]))


def cmd_intake_group(args):
    index = _load(args.path)
    book_mod.add_group(
        index, args.group, args.day, args.version, args.origin,
        args.size, args.rest_min, args.state,
    )
    book_mod.save(index, args.path)
    _print({"added": "group", "group": args.group, "groups": len(index["groups"])})


def cmd_intake_record(args):
    index = _load(args.path)
    groups = args.groups.split(",")
    book_mod.add_station_record(
        index, args.ref, groups, args.station, args.in_at, args.out_at, args.known_seq
    )
    book_mod.save(index, args.path)
    _print({"added": "station_record", "ref": args.ref, "groups": groups})


def cmd_ledger_init(args):
    index = _load(args.path)
    ledger = ledger_mod.init_ledger(index)
    ledger_mod.save_ledger(ledger, args.ledger)
    _print({"initialized": args.ledger, "commitments": len(ledger["commitments"])})


def cmd_plan(args):
    index = _load(args.path)
    ledger = _ledger_or_die(args.ledger)
    scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    chains = build_chains(index)
    scenarios = scenario.get("scenarios", [scenario])
    results = [evaluate_scenario(index, chains, ledger, sc) for sc in scenarios]
    _print({"results": results})


def cmd_issue(args):
    index = _load(args.path)
    ledger = _ledger_or_die(args.ledger)
    scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    if "scenarios" in scenario:
        raise SystemExit("issue 一次只能签发一个方案，请传入含 scenario/groups/assignments 的单方案文件")
    chains = build_chains(index)
    result = evaluate_scenario(index, chains, ledger, scenario)
    issue = issue_scenario(index, chains, ledger, result, scenario)
    ledger_mod.save_ledger(ledger, args.ledger)
    _print({"evaluation": result, "issue": issue})


def cmd_capacity(args):
    index = _load(args.path)
    ledger = _ledger_or_die(args.ledger)
    _print({"slots": ledger_mod.capacity_view(index, ledger)})


def cmd_recheck(args):
    before = _load(args.before)
    after = _load(args.after)
    ledger = _ledger_or_die(args.ledger)
    _print(recheck(before, after, ledger))


def cmd_audit(args):
    index = _load(args.path)
    ledger = _ledger_or_die(args.ledger)
    chains = build_chains(index)
    _print(audit_group(index, chains, ledger, args.group))


def build_parser():
    parser = argparse.ArgumentParser(description="研学联程完成机会、试算与签发")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("tables", help="列出各表记录数")
    p.add_argument("path")
    p.set_defaults(func=cmd_tables)

    p = sub.add_parser("report", help="全程完成机会与交接损失报告")
    p.add_argument("path")
    p.add_argument("--origin", help="按出发站过滤")
    p.add_argument("--rest-min", type=int, help="只看照护间隔不小于该值的家庭")
    p.add_argument("--version", help="按行程版本过滤")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("chain", help="单团全程链路详情")
    p.add_argument("path")
    p.add_argument("--group", required=True)
    p.set_defaults(func=cmd_chain)

    p = sub.add_parser("intake-group", help="录入新团期到工作簿")
    p.add_argument("path")
    p.add_argument("--group", required=True)
    p.add_argument("--day", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--origin", required=True)
    p.add_argument("--size", required=True, type=int)
    p.add_argument("--rest-min", required=True, type=int)
    p.add_argument("--state", required=True, choices=sorted(book_mod.GROUP_STATES))
    p.set_defaults(func=cmd_intake_group)

    p = sub.add_parser("intake-record", help="录入分站接待凭证")
    p.add_argument("path")
    p.add_argument("--ref", required=True)
    p.add_argument("--groups", required=True, help="候选团，逗号分隔")
    p.add_argument("--station", required=True)
    p.add_argument("--in-at", required=True, dest="in_at")
    p.add_argument("--out-at", dest="out_at")
    p.add_argument("--known-seq", required=True, type=int, dest="known_seq")
    p.set_defaults(func=cmd_intake_record)

    p = sub.add_parser("ledger-init", help="从换场通知初始化签发台账")
    p.add_argument("path")
    p.add_argument("--ledger", required=True)
    p.set_defaults(func=cmd_ledger_init)

    p = sub.add_parser("plan", help="一批备选接驳方案试算（不写台账）")
    p.add_argument("path")
    p.add_argument("--ledger", required=True)
    p.add_argument("--scenario", required=True)
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("issue", help="试算并签发可执行方案，写台账")
    p.add_argument("path")
    p.add_argument("--ledger", required=True)
    p.add_argument("--scenario", required=True)
    p.set_defaults(func=cmd_issue)

    p = sub.add_parser("capacity", help="同一班次剩余可承接人数对账")
    p.add_argument("path")
    p.add_argument("--ledger", required=True)
    p.set_defaults(func=cmd_capacity)

    p = sub.add_parser("recheck", help="补回回执后复检剩余可调团")
    p.add_argument("--before", required=True)
    p.add_argument("--after", required=True)
    p.add_argument("--ledger", required=True)
    p.set_defaults(func=cmd_recheck)

    p = sub.add_parser("audit", help="逐团查清签发依据、选择与未换原因")
    p.add_argument("path")
    p.add_argument("--ledger", required=True)
    p.add_argument("--group", required=True)
    p.set_defaults(func=cmd_audit)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
