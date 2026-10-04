"""Persist frontend/backend consistency and preserve historical strategy counts."""
import hashlib
import json
import sqlite3
from pathlib import Path

import psutil

ROOT = Path(r"D:\codex\CodexWork\clash")
before = json.loads((ROOT / "work/backups/random-mastery-20260930/ui-history-before.json").read_text())
connection = sqlite3.connect(ROOT / "outputs/cn-battle-history.sqlite3")
counts = dict(connection.execute("SELECT strategy,COUNT(*) FROM battles GROUP BY strategy"))
random_results = dict(connection.execute("SELECT result,COUNT(*) FROM battles WHERE strategy='random' GROUP BY result"))
connection.close()
live = json.loads((ROOT / "outputs/random-mastery-live-status.json").read_text(encoding="utf-8"))
running = psutil.Process(live["pid"])
verified_runner = "run_cn_1v1.py" in " ".join(running.cmdline()) and running.is_running()
error_log = ROOT / "work/control-ui-random-final-stderr.log"
sources = [ROOT / "py-clash-bot/scripts/cn_bot_control.py", ROOT / "py-clash-bot/pyclashbot/utils/battle_history.py"]
report = {
    "accepted": verified_runner and all(counts.get(key) == value for key, value in before.items())
                and counts.get("random", 0) > 0 and error_log.stat().st_size == 0,
    "live_status": live,
    "frontend_observed": {"selected_scope": "随机卡组", "refresh_seconds": 2,
                          "observed_count_advance": [7, 8, 10],
                          "observed_claim_all_batches": 1,
                          "start_disabled_while_running": True,
                          "stop_enabled_while_running": True},
    "history_before": before, "history_after": counts,
    "old_history_preserved": all(counts.get(key) == value for key, value in before.items()),
    "random_results": random_results,
    "tests": {"passed": 50, "command": "python -m pytest tests/test_cn_random_mastery.py tests/test_battle_history.py tests/test_cn_control_random.py -q"},
    "source_sha256": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
    "rollback": "Stop the runner if reverting the mode; restore cn_bot_control.py and battle_history.py from work/backups/random-mastery-20260930, then reopen the control window. The original game logs and fixed-deck history remain preserved.",
}
target = ROOT / "outputs/RANDOM_MASTERY_FRONTEND_ACCEPTANCE.json"
target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"accepted": report["accepted"], "history_after": counts, "completed": live["completed"],
                  "generated_decks": live["generated_decks"], "claim_all_batches": live["claim_all_batches"]}, ensure_ascii=False))
