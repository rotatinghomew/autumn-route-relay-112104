"""命令行入口：python3 -I run.py <子命令> ..."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from yanxue.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
