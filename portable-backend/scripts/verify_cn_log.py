# ruff: noqa: RUF001
# Native Chinese punctuation and multiplication glyphs are intentional UI/OCR text.
"""Independently check the persisted 10-cycle Tencent battle acceptance log."""

import argparse
import json
import re
from pathlib import Path

START = re.compile(r"^(\S+ \S+) INFO 对战开始 场次=\d+")
END = re.compile(r"^(\S+ \S+) INFO 对战结束 结果=(\S+) 出牌确认=(\d+)/(\d+) 已完成=(\d+) 连续完成=(\d+)")
RECOVERY = ("恢复/重启", "恢复事件：战斗中意外返回大厅", "连续验收重新计数")


def verify(lines: list[str]) -> dict:
    starts = 0
    ends = 0
    recoveries = 0
    active = False
    streak = 0
    last_end: dict | None = None
    cycles: list[dict] = []

    for line in lines:
        if any(marker in line for marker in RECOVERY):
            recoveries += 1
            active = False
            streak = 0
            last_end = None
            continue

        start_match = START.search(line)
        if start_match:
            starts += 1
            if active:
                streak = 0  # a second start without a verified end breaks the chain
            if last_end is not None:
                last_end["next_started"] = True
            active = True
            continue

        end_match = END.search(line)
        if end_match:
            ends += 1
            confirmed = int(end_match.group(3))
            attempts = int(end_match.group(4))
            valid = active and 0 < confirmed <= attempts
            streak = streak + 1 if valid else 0
            cycle = {
                "ended_at": end_match.group(1),
                "result": end_match.group(2),
                "cards_confirmed": confirmed,
                "card_attempts": attempts,
                "valid": valid,
                "verified_streak": streak,
                "next_started": False,
            }
            cycles.append(cycle)
            last_end = cycle if valid else None
            active = False

    accepted = next((cycle for cycle in cycles if cycle["verified_streak"] >= 10 and cycle["next_started"]), None)
    return {
        "accepted": accepted is not None,
        "start_count": starts,
        "end_count": ends,
        "recovery_count": recoveries,
        "maximum_verified_streak": max((cycle["verified_streak"] for cycle in cycles), default=0),
        "tenth_cycle_end": accepted["ended_at"] if accepted else None,
        "next_battle_started_after_tenth": bool(accepted),
        "latest_cycles": cycles[-12:],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.log.read_text(encoding="utf-8").splitlines())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "latest_cycles"}, ensure_ascii=False))
    raise SystemExit(0 if report["accepted"] else 1)


if __name__ == "__main__":
    main()
