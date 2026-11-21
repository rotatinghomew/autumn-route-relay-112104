"""同一天 HH:MM 时刻的解析与比较。

空值一律用 None 表示“未观测”，绝不臆造成具体时刻。
"""
from __future__ import annotations


def parse_hm(value):
    """把 HH:MM 解析为分钟数；None 透传。"""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"时刻格式应为 HH:MM：{value!r}")
    hour, _, minute = value.partition(":")
    if not minute or len(hour) != 2 or len(minute) != 2:
        raise ValueError(f"时刻格式应为 HH:MM：{value!r}")
    h, m = int(hour), int(minute)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"时刻越界：{value!r}")
    return h * 60 + m


def hm(minutes):
    if minutes is None:
        return None
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def overlaps(start_a, end_a, start_b, end_b):
    """闭区间是否有交集；任一端未知则无法证明重叠，返回 False。"""
    if None in (start_a, end_a, start_b, end_b):
        return False
    return start_a <= end_b and start_b <= end_a
