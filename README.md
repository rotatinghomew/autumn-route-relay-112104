# 研学联程中的可完成体验率与接驳时刻

线路运营与团长使用团期、站点记录及已签发的换场凭证核对接驳。时刻为团期所在地 HH:MM，同一天；空时刻表示未观测。

## 资料交换

`data/samples.json` 是合成样册。`fields` 给出有序列名，`rows` 按该顺序记录数据，`meaning` 标明单位或来源区别。没有填写的值用 `null` 表示。

- `groups`：需求按团；state 区分已结束、提前结束、等待和观察未满。 列：`group`, `day`, `version`, `origin`, `size`, `rest_min`, `state`。
- `stations`：group_choices 为时空可能匹配的团；known_seq 为获知顺序。 列：`ref`, `group_choices`, `station`, `in_at`, `out_at`, `known_seq`。
- `services`：走到本场地所需的最短时间。 列：`version`, `station`, `start`, `end`, `walk_min`。
- `offers`：同名 slot 表示同一实际场次，另日场次不能承接本日。 列：`option`, `slot`, `day`, `time`, `capacity`, `eligible_groups`。
- `notices`：accepted 为团长确实确认的替代；空表示没有确认。 列：`notice`, `group`, `slot`, `size`, `alternate`, `accepted`, `seq`。

## 检视

使用 Python 3.11，资料读取不依赖第三方包。

```sh
python3 source_book.py data/samples.json
python3 -m unittest discover -s tests -v
```

资料读取命令列出各表记录数；测试检查交叉引用与格式，不生成分析结果。
