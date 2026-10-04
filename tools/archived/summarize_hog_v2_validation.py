"""Read-only analysis of fixed completed battle cohorts; writes only its report."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
FORMAT = "%Y-%m-%d %H:%M:%S"
COHORTS = {
    "20260925-232740": ("2026-09-25 23:27:40", "hog-v2-20260925", [1, 2, 3, 4, 5]),
    "20260925-234557": ("2026-09-25 23:45:57", "hog-v2.1-20260925", [2, 3, 4]),
}
MANUAL_REVIEWS = {
    ("20260925-232740", 5): {"result": "失败", "score": None},
    ("20260925-234557", 3): {"result": "失败", "score": "0:1"},
    ("20260925-234557", 4): {"result": "失败", "score": "1:3"},
}


def summarize(rows: list[dict], durations: dict[int | str, float]) -> dict:
    plays = [row for row in rows if row["event"] == "play"]
    confirmed = [row for row in plays if row["confirmed"]]
    defense = [row for row in confirmed if row["decision"]["category"] == "defense"]
    cheap = [row for row in defense if row["decision"]["card"] in ("skeletons", "ice_spirit")]
    hogs = [row for row in confirmed if row["decision"]["card"] == "hog"]
    new_rule = [row for row in plays if row["decision"]["reason"] == "已有防守核心，先用1费拖延等待输出"]
    abilities = [row for row in rows if row["event"] == "elite_ability"]
    ends = [row for row in rows if row["event"] == "battle_end"]
    seconds = sum(durations.values())
    return {
        "completed": len(ends),
        "automatic_outcomes": dict(Counter(row["result"] for row in ends)),
        "battle_seconds": seconds,
        "battle_minutes": seconds / 60,
        "card_attempts": len(plays),
        "card_confirmed": len(confirmed),
        "card_confirmation_rate": len(confirmed) / len(plays),
        "hog_confirmed": len(hogs),
        "hog_per_battle_minute": len(hogs) * 60 / seconds,
        "confirmed_defense_cards": len(defense),
        "confirmed_one_elixir_defense": len(cheap),
        "one_elixir_share_of_confirmed_defense": len(cheap) / len(defense),
        "existing_core_one_elixir_rule_attempts": len(new_rule),
        "existing_core_one_elixir_rule_confirmed": sum(row["confirmed"] for row in new_rule),
        "fireball_attempts": sum(row["decision"]["card"] == "fireball" for row in plays),
        "fireball_confirmed": sum(row["decision"]["card"] == "fireball" for row in confirmed),
        "elite_ability_attempts": len(abilities),
        "elite_ability_confirmed": sum(row["confirmed"] for row in abilities),
        "confirmed_by_category_card": dict(Counter(
            row["decision"]["category"] + "/" + row["decision"]["card"] for row in confirmed
        )),
    }


def process_state() -> dict:
    state = json.loads((ROOT / "work/bot-processes.json").read_text(encoding="utf-8"))
    alive = {}
    for name, script in (("watchdog", "watch_cn_1v1.py"), ("runner", "run_cn_1v1.py")):
        try:
            proc = psutil.Process(int(state[name + "_pid"]))
            alive[name] = proc.is_running() and script in " ".join(proc.cmdline())
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            alive[name] = False
    return {"state": "running" if all(alive.values()) else "starting" if alive["watchdog"] else "stopped", **alive}


def main() -> None:
    trace_path = ROOT / "outputs/cn-hog-strategy.jsonl"
    log_path = ROOT / "outputs/cn-battles-live.log"
    trace_bytes, log_bytes = trace_path.read_bytes(), log_path.read_bytes()
    trace = [json.loads(line) for line in trace_bytes.decode("utf-8").splitlines() if line.strip()]
    starts, hashes = {}, {}
    session_start = None
    for line in log_bytes.decode("utf-8").splitlines():
        if "连续对战已启动" in line:
            session_start = line[:19]
        if "策略源码校验: " in line:
            hashes[session_start] = ast.literal_eval(line.split("策略源码校验: ", 1)[1])
        match = re.search(r"对战开始 场次=(\d+)", line)
        if match:
            starts[session_start, int(match[1])] = datetime.strptime(line[:19], FORMAT).timestamp()
    cohorts, all_rows, all_durations, manual = [], [], {}, []
    for session, (started, policy, battle_ids) in COHORTS.items():
        rows = [row for row in trace if row.get("session") == session and row.get("policy_version") == policy]
        ends = [row for row in rows if row["event"] == "battle_end" and row["battle"] in battle_ids]
        assert sorted(row["battle"] for row in ends) == battle_ids, "Expected completed cohort is missing"
        cutoff = max(row["time"] for row in ends)
        rows = [row for row in rows if row["battle"] in battle_ids and row["time"] <= cutoff]
        durations = {row["battle"]: datetime.strptime(row["time"], FORMAT).timestamp() - starts[started, row["battle"]] for row in ends}
        metrics = summarize(rows, durations)
        assert metrics["card_attempts"] == sum(row["attempts"] for row in ends)
        assert metrics["card_confirmed"] == sum(row["confirmed"] for row in ends)
        resolved = []
        for end in ends:
            key = session, end["battle"]
            review = MANUAL_REVIEWS.get(key)
            resolved.append(review["result"] if review else end["result"])
            if review:
                screenshot = ROOT / "work/hog-validation" / session / f"result-{end['battle']:02d}.png"
                assert screenshot.is_file()
                manual.append({"session": session, "battle": end["battle"], "automatic_result": end["result"], "reviewed_result": review["result"], "score_our_opponent": review["score"], "reviewer": "root agent visual review, supplied to audit agent", "screenshot": str(screenshot), "screenshot_sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest()})
        metrics.update({"session": session, "policy_version": policy, "included_battles": battle_ids, "cutoff": cutoff, "runtime_source_hashes_from_startup_log": hashes[started], "outcomes_after_manual_resolution": dict(Counter(resolved))})
        cohorts.append(metrics)
        all_rows.extend(rows)
        all_durations.update({f"{session}/{battle}": seconds for battle, seconds in durations.items()})
    aggregate = summarize(all_rows, all_durations)
    resolved_counts = Counter()
    for cohort in cohorts:
        resolved_counts.update(cohort["outcomes_after_manual_resolution"])
    aggregate["outcomes_after_manual_resolution"] = dict(resolved_counts)
    baseline = json.loads((ROOT / "work/v2-live-comparison.json").read_text(encoding="utf-8"))["before"]
    report = {
        "created_at": datetime.now().strftime(FORMAT),
        "status": "NO_EVIDENCE_OF_WIN_RATE_IMPROVEMENT",
        "baseline": baseline,
        "baseline_limitations": ["Old baseline has no source hashes; startup grouping and trace reasons establish chronology only.", "The 14 unknown baseline outcomes are not relabeled as losses."],
        "cohorts": cohorts,
        "aggregate_complete_live_tests": aggregate,
        "manual_screenshot_reviews": manual,
        "excluded": [{"session": "20260925-232740", "battle": 6, "reason": "Incomplete interrupted battle"}, {"session": "20260925-234557", "battle": 1, "reason": "Resumed remainder of existing battle, 0/0 card attempts; not a complete independent test"}],
        "current_bot_state": process_state(),
        "stopped_after_final_battle": "2026-09-25 23:54:56; stop operation reported by root agent, current process state read independently",
        "definitions": {"battle_minutes": "Sum of battle start to battle_end durations, excluding lobby/matchmaking; timestamp precision 1 second.", "one_elixir_defense_share": "Confirmed skeletons/ice_spirit category=defense divided by all confirmed defense; spells excluded.", "confirmation_rate": "Confirmed play events / play attempts; ability taps excluded."},
        "limitations": ["Eight complete tests are all losses after screenshot resolution. This is no evidence of improved win rate; small nonrandom cohorts cannot establish causal effects.", "No elite-ability attempts occurred; the skill is not live-validated by these tests.", "Automatic outcomes and manual screenshot reviews are kept separate. Runtime log hashes are not replaced by hashes of post-run files."],
        "offline_tests": {"passed": 51, "source": "root agent final unittest rerun", "result": "Ran 51 tests in 0.005s; OK", "final_product_py_compile": "Root agent will run and report separately"},
        "post_run_result_template_patch": {"status": "offline validation pending", "note": "Another agent is correcting the yellow result template after runtime; no effect on recorded gameplay cohorts or preserved runtime hashes."},
        "rollback_backup": str(ROOT / "work/backups/hog-v2-20260925-231041"),
        "input_snapshot_sha256": {str(trace_path): hashlib.sha256(trace_bytes).hexdigest(), str(log_path): hashlib.sha256(log_bytes).hexdigest()},
    }
    destination = ROOT / "outputs/hog-v2-validation.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(destination), "cohorts": cohorts, "aggregate": aggregate, "state": report["current_bot_state"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
