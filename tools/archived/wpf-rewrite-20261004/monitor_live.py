"""Observe appended bot events; never send input or launch/stop the bot."""

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psutil

REPO = Path(__file__).resolve().parents[2] / "py-clash-bot"
sys.path.insert(0, str(REPO))
from pyclashbot.utils.persistence import atomic_write_json

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"
MONITOR = WORK / "live-monitor.json"
SHANGHAI = timezone(timedelta(hours=8))
FLOW_EVENTS = {
    "started", "startup_ready", "battle_resumed", "deck_generated", "match_requested", "battle_started", "play",
    "battle_finished", "result_committed", "returned_lobby", "mastery_opened", "mastery_footer_checked", "mastery_checked",
    "claim_all_attempt", "claim_all_confirmed", "claim_all_unverified", "reward_observed", "cycle_complete", "paused",
    "recovery_attempt", "battle_recovered", "screen_mismatch", "user_stopped", "finite_complete",
}


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return {"read_error": str(error)}


def process_identity(pid, created=None, *, component=None):
    answer = {"pid": pid, "expected_created_at": created, "alive": False}
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        answer["error"] = "Missing process id"
        return answer
    try:
        proc = psutil.Process(pid)
        answer.update(alive=proc.is_running(), executable=proc.exe(), created_at=proc.create_time())
        expected = OUTPUTS / "wpf-desktop-20261004" / ("backend/ClashBackend.exe" if created is not None or component == "backend" else "app/ClashAssistant.Desktop.exe")
        answer["new_desktop_executable"] = Path(answer["executable"]).resolve() == expected.resolve()
        answer["creation_time_matches"] = created is None or abs(answer["created_at"] - created) < 0.02
    except (psutil.Error, TypeError, ValueError) as error:
        answer["error"] = type(error).__name__
    return answer


def appended(path, offset, limit=2 * 1024 * 1024):
    with path.open("rb") as stream:
        stream.seek(offset)
        raw = stream.read(limit)
    end = raw.rfind(b"\n")
    if end < 0:
        return offset, []
    complete = raw[:end + 1]
    lines = []
    position = offset
    for line in complete.splitlines(keepends=True):
        lines.append((position, position + len(line), line.decode("utf-8", errors="replace").rstrip()))
        position += len(line)
    return offset + len(complete), lines


baseline = read_json(WORK / "live-baseline.json")
if MONITOR.is_file():
    monitor = read_json(MONITOR)
else:
    monitor = {
        "schema": 1, "baseline_at": baseline["captured_at"], "baseline_trace_offset": baseline["trace_bytes"],
        "trace_offset": baseline["trace_bytes"], "watchdog_offset": baseline["watchdog_log_bytes"],
        "observations": [], "battles": {}, "flow_events": [], "watchdog_new_lines": [], "malformed_new_lines": [],
        "pass_condition": "At least three post-baseline matched, started, confirmed-play, settled, returned, mastery-checked, completed new cycles with next-battle start proof; resumed prior battles are excluded.",
        "read_only_game_observation": True,
    }

offset, lines = appended(OUTPUTS / "cn-random-mastery.jsonl", monitor["trace_offset"])
new_flow = []
for start, end, line in lines:
    try:
        event = json.loads(line)
    except ValueError:
        monitor["malformed_new_lines"].append({"offset_start": start, "offset_end": end})
        continue
    if event.get("event") not in FLOW_EVENTS:
        continue
    event["trace_offset_start"], event["trace_offset_end"] = start, end
    monitor["flow_events"].append(event)
    new_flow.append(event)
    key = f"{event.get('session')}:{event.get('battle')}"
    battle = monitor["battles"].setdefault(key, {"session": event.get("session"), "battle": event.get("battle"), "events": {}, "confirmed_play_events": 0, "attempted_play_events": 0})
    kind = event["event"]
    if kind == "play":
        battle["attempted_play_events"] += 1
        battle["confirmed_play_events"] += int(event.get("confirmed") is True)
    else:
        battle["events"][kind] = event
    if kind == "battle_finished":
        evidence = event.get("evidence") or {}
        evidence_path = Path(evidence.get("path", ""))
        verified = {"path": str(evidence_path), "expected_sha256": evidence.get("sha256"), "exists": evidence_path.is_file()}
        if verified["exists"] and evidence_path.resolve().is_relative_to(ROOT):
            verified["actual_sha256"] = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            verified["sha256_matches"] = verified["actual_sha256"] == verified["expected_sha256"]
        else:
            verified["sha256_matches"] = False
        battle["result_evidence"] = verified
monitor["trace_offset"] = offset
watch_offset, watch_lines = appended(OUTPUTS / "cn-watchdog.log", monitor["watchdog_offset"])
monitor["watchdog_offset"] = watch_offset
monitor["watchdog_new_lines"].extend({"offset_start": start, "offset_end": end, "line": text} for start, end, text in watch_lines)

live = read_json(OUTPUTS / "random-mastery-live-status.json")
pids = read_json(ROOT / "work" / "bot-processes.json")
ui = read_json(ROOT / "work" / "wpf-desktop" / "frontend-state.json")
if "read_error" in ui:
    ui = {"pid": baseline.get("ui", {}).get("pid") or baseline.get("ui_pid"), "state": "not_exported"}
now = datetime.now(SHANGHAI).isoformat(timespec="seconds")
observation = {
    "observed_at": now, "new_trace_lines": len(lines), "new_flow_events": len(new_flow), "live": live, "process_state": pids,
    "process_identity": {
        "ui": process_identity(ui.get("pid")),
        "bridge": process_identity(baseline.get("bridge_pid", 3924), component="backend"),
        "watchdog": process_identity(pids.get("watchdog_pid"), pids.get("watchdog_created_at")),
        "runner": process_identity(pids.get("runner_pid"), pids.get("runner_created_at")),
    },
    "ui": {key: ui.get(key) for key in ("updated_at", "pid", "state", "phase", "frontend_language", "framework", "preview", "visible", "backend_running", "backend_path", "metrics", "report_count", "emulator", "tray")},
}
monitor["observations"].append(observation)
completed = []
settled_cycles = []
excluded = []
for key, battle in monitor["battles"].items():
    events = battle["events"]
    if "battle_resumed" in events or (events.get("cycle_complete") or {}).get("resumed"):
        excluded.append({"session": battle["session"], "battle": battle["battle"], "reason": "Resumed pre-baseline battle; no new matching and full new-battle start."})
        continue
    required = {"deck_generated", "match_requested", "battle_started", "battle_finished", "returned_lobby", "mastery_checked", "cycle_complete"}
    if not required.issubset(events) or not battle["confirmed_play_events"] or not battle.get("result_evidence", {}).get("sha256_matches"):
        continue
    settled_cycles.append({"session": battle["session"], "battle": battle["battle"], "result": events["battle_finished"].get("outcome"), "card_attempts": events["battle_finished"].get("card_attempts"), "cards_confirmed": events["battle_finished"].get("cards_confirmed"), "cycle_complete_at": events["cycle_complete"]["time"], "result_evidence": battle["result_evidence"]})
    next_battle = monitor["battles"].get(f"{battle['session']}:{battle['battle'] + 1}", {})
    next_start = (next_battle.get("events") or {}).get("battle_started")
    if not next_start:
        continue
    result = events["battle_finished"]
    completed.append({
        "session": battle["session"], "battle": battle["battle"], "generation": result.get("generation"), "result": result.get("outcome"),
        "card_attempts": result.get("card_attempts"), "cards_confirmed": result.get("cards_confirmed"),
        "observed_attempts": battle["attempted_play_events"], "observed_confirmed": battle["confirmed_play_events"],
        "matched_at": events["match_requested"]["time"], "started_at": events["battle_started"]["time"], "settled_at": result["time"],
        "returned_lobby_at": events["returned_lobby"]["time"], "mastery_check_at": events["mastery_checked"]["time"], "mastery_check": events["mastery_checked"],
        "cycle_complete_at": events["cycle_complete"]["time"], "result_evidence": battle["result_evidence"],
        "next_battle": {"battle": next_start["battle"], "session": next_start["session"], "started_at": next_start["time"], "trace_offset_start": next_start["trace_offset_start"]},
    })
monitor["completed_new_battles"] = completed
monitor["settled_new_cycles"] = settled_cycles
monitor["excluded_resumed_battles"] = excluded
if pids.get("phase") == "stopped":
    monitor["termination"] = {"exit_reason": pids.get("exit_reason"), "ended_at": pids.get("ended_at"), "finite_complete": next((event for event in reversed(monitor["flow_events"]) if event["event"] == "finite_complete"), None)}
monitor["anomalies"] = {
    "pause_events": [event for event in monitor["flow_events"] if event["event"] == "paused"],
    "restore_events": [event for event in monitor["flow_events"] if event["event"] in {"recovery_attempt", "battle_recovered", "screen_mismatch"}],
    "watchdog_error_lines": [row for row in monitor["watchdog_new_lines"] if any(token in row["line"] for token in (" ERROR ", "Traceback", "运行器退出", "停止自动恢复"))],
    "currently_paused": pids.get("phase") == "paused" or live.get("state") == "paused",
    "process_identity_failed": [name for name, identity in observation["process_identity"].items() if name in {"watchdog", "runner"} and not (identity.get("alive") and identity.get("new_desktop_executable") and identity.get("creation_time_matches"))],
}
if monitor["anomalies"]["currently_paused"]:
    monitor["latest_error_report"] = read_json(OUTPUTS / "error-reports" / "latest-error-report.json")
monitor["passed"] = len(completed) >= 3 and not monitor["anomalies"]["pause_events"] and not monitor["anomalies"]["currently_paused"] and not monitor["anomalies"]["restore_events"] and not monitor["anomalies"]["watchdog_error_lines"] and not monitor["anomalies"]["process_identity_failed"]
monitor["updated_at"] = now
atomic_write_json(MONITOR, monitor)
print(json.dumps({"observed_at": now, "session": live.get("session"), "state": live.get("state"), "live_completed": live.get("completed"), "card_attempts": live.get("card_attempts"), "cards_confirmed": live.get("cards_confirmed"), "completed_new": [{key: row[key] for key in ("battle", "result", "card_attempts", "cards_confirmed", "next_battle")} for row in completed], "excluded": excluded, "anomalies": monitor["anomalies"], "passed": monitor["passed"]}, ensure_ascii=False))
