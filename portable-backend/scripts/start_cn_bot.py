"""Start the configured console runner without duplicating an existing owner."""

# Native Chinese status text intentionally retains full-width punctuation.
# ruff: noqa: RUF001

import argparse
import sys
from pathlib import Path

# Direct script launches also work with the preserved older editable install.
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyclashbot.utils.persistence import atomic_write_bytes
from scripts.cn_bot_control import STRATEGY_SELECTION, ControlWindow, bot_state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", choices=("567", "hog", "random"), default="random")
    parser.add_argument("--max-battles", type=int, default=0)
    args = parser.parse_args()
    if args.max_battles < 0:
        parser.error("--max-battles must be nonnegative")
    if bot_state() not in ("stopped", "paused"):
        print("机器人已在运行，未创建第二个守护进程。")
        return
    atomic_write_bytes(STRATEGY_SELECTION, args.strategy.encode("utf-8"))
    print(ControlWindow._start_worker(max_battles=args.max_battles))


if __name__ == "__main__":
    main()
