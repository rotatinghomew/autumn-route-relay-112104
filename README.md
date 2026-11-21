# 研学联程中的可完成体验率与接驳时刻

线路运营与团长使用团期、站点记录及已签发的换场凭证核对接驳。时刻为团期所在地 HH:MM，同一天；空时刻表示未观测。

## 资料交换

`data/samples.json` 是合成样册。`fields` 给出有序列名，`rows` 按该顺序记录数据，`meaning` 标明单位或来源区别。没有填写的值用 `null` 表示。

- `groups`：需求按团；state 区分已结束、提前结束、等待和观察未满。 列：`group`, `day`, `version`, `origin`, `size`, `rest_min`, `state`。
- `stations`：group_choices 为时空可能匹配的团；known_seq 为获知顺序。 列：`ref`, `group_choices`, `station`, `in_at`, `out_at`, `known_seq`。
- `services`：走到本场地所需的最短时间。 列：`version`, `station`, `start`, `end`, `walk_min`。
- `offers`：同名 slot 表示同一实际场次，另日场次不能承接本日。 列：`option`, `slot`, `day`, `time`, `capacity`, `eligible_groups`。
- `notices`：accepted 为团长确实确认的替代；空表示没有确认。 列：`notice`, `group`, `slot`, `size`, `alternate`, `accepted`, `seq`。

## 模型口径（不可违反的规则）

1. **证据归属**：同站时空相撞的凭证互相排除独占候选；剩余多个候选保持“待定”，不复制成两次到达；只有一个候选才是“确定”。
2. **缺报不等于缺席**：出站缺报但下一站凭证证明已到达时，离开时刻给区间 `[到达时刻, 下站到达−步行时间]`，并注明依据是确定还是待定凭证。
3. **状态分流**：提前结束、等待改签、观察未满与失败分开计数；失败只来自步行时间不可能成立的断裂交接，未观察的团既不算成功也不算失败。
4. **完成机会是区间**：按联程凭证统计“确定完成数/可能完成数”形成区间，**绝不把各站独立准点率相乘**。
5. **不可作的比较**：共享待定凭证的团之间不能比准点；结局未观察的团不能与完结团比完成率；关键时刻缺报的交接不列排名。
6. **试算不等于承诺**：换早班同时校验最短步行与团的 `rest_min` 照护间隔；共享补救场次余位只扣一次；存在待定归属或未知时间且足以反转推荐时，结果标记 `recommendation_reversible`，禁止签发。
7. **签发保护**：已发到团长手上的时间只能按其确认过（`accepted`）的换场协议变更；待确认改签只保守占位、不得执行；无法安置的原承诺继续占位并列为冲突；历史签发不随补证复检改写，只追加新签发。

## 使用

Python 3.11，无第三方依赖。建议以隔离模式运行：

```sh
python3 -I source_book.py data/samples.json           # 各表记录数
python3 -I run.py report data/samples.json            # 全程完成机会区间与交接损失
python3 -I run.py report data/samples.json --origin 东门 --rest-min 20 --version v1
python3 -I run.py chain data/samples.json --group A   # 单团逐站证据与交接
python3 -I -m unittest discover -s tests -v
```

### 录入新团期与凭证（写工作簿副本，原样册保持只读）

```sh
cp data/samples.json work.json
python3 -I run.py intake-group work.json --group F --day 2026-11-14 \
    --version v1 --origin 北门 --size 3 --rest-min 15 --state 等待
python3 -I run.py intake-record work.json --ref q1 --groups F \
    --station 讲堂 --in-at 09:10 --out-at 10:00 --known-seq 1
```

### 台账、试算、签发与对账

```sh
python3 -I run.py ledger-init data/samples.json --ledger ledger.json
python3 -I run.py capacity data/samples.json --ledger ledger.json
# 方案文件：{"scenario": "...", "groups": ["A","B"], "assignments": {"A": "补一", "B": "车甲"}}
python3 -I run.py plan data/samples.json --ledger ledger.json --scenario scenarios.json
python3 -I run.py issue data/samples.json --ledger ledger.json --scenario scenarios.json
python3 -I run.py audit data/samples.json --ledger ledger.json --group D
```

`capacity` 对同一班次同时列出**原签发、已接受替代、待确认改签**三类占位，并给两个剩余口径：
`remaining_conservative`（待确认先占）与 `remaining_if_pending_rejected`（待确认被退回）。

### 补回回执后的复检

```sh
python3 -I run.py recheck --before data/samples.json --after work.json --ledger ledger.json
```

只报告结论确实被新证据改变的团，并逐团给出现有可行选择与不能换的原因；台账历史不被改写。

## 代码结构

- `yanxue/book.py`：装载、结构/引用校验、保存、新团期录入。
- `yanxue/timeutil.py`：HH:MM 解析与区间重叠。
- `yanxue/evidence.py`：凭证归属、缺报离开区间、联程重建与状态分流。
- `yanxue/reliability.py`：完成机会区间、交接损失、不可作比较、单团详情。
- `yanxue/ledger.py`：签发台账、三类占位、班次余位对账。
- `yanxue/planning.py`：最早可登车时刻、方案试算、签发与逐团审计。
- `yanxue/recheck.py`：补证复检与剩余可调团检验。
- `yanxue/cli.py` / `run.py`：命令行入口。
