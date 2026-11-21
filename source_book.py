"""读取资料并核对表头、行宽和基础引用（兼容入口，实现见 yanxue.book）。"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from yanxue.book import load  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="查看本地交换资料的表名和行数")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    print(json.dumps({name: len(rows) for name, rows in load(args.path).items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
