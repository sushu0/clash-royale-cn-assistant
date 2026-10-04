"""Read-only acceptance evidence for the deployed infinite Classic 1v1 bot."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psutil

TASK = Path(__file__).resolve().parent
ROOT = TASK.parents[1]
BACKEND = ROOT / "outputs/wpf-desktop-navigation-20261004/backend/ClashBackend.exe"
POLICY = "random-mastery-v25-learned-navigation-20261004"
SHANGHAI = timezone(timedelta(hours=8))
RUNTIME_SOURCES = (
    "bot/cn_random_mastery_loop.py", "bot/cn_1v1_loop.py", "bot/coords.py", "bot/nav.py", "bot/state_detect.py",
    "bot/random_deck_strategy.py", "bot/random_card_roles.py", "detection/cn_random_hand.py",
    "detection/cn_random_deployment.py", "detection/cn_random_ui.py", "detection/cn_daily_gift.py",
    "detection/cn_page_navigation.py", "utils/cn_footer_ocr.py", "utils/persistence.py", "utils/runtime_config.py",
)


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    path = path.resolve()
    if not path.is_relative_to(TASK):
        raise ValueError("Acceptance records must remain in the task work directory")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def reports():
    return {
        str(path.relative_to(ROOT)): digest(path)
        for path in sorted((ROOT / "outputs/error-reports").rglob("*"))
        if path.is_file() and path.suffix.lower() in {".png", ".json", ".md"}
    }


def protected_frontend():
    baseline = read(TASK / "deployment-baseline.json")
    return {
        key: digest(Path(baseline["files"][key]["path"]))
        for key in ("executable", "assembly", "shortcut")
    }


def snapshot():
    return {
        "time": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
        "checkpoint": read(ROOT / "work/random-mastery/checkpoint.json"),
        "status": read(ROOT / "outputs/random-mastery-live-status.json"),
        "process_record": read(ROOT / "work/bot-processes.json"),
        "frontend": read(ROOT / "work/wpf-desktop/frontend-state.json"),
    }


def process_evidence(record):
    result = {}
    for role in ("watchdog", "runner"):
        pid = record.get(role + "_pid")
        try:
            recorded_start = record.get(role + "_created_at")
            if type(pid) is not int or pid <= 0 or not isinstance(recorded_start, (int, float)) or not math.isfinite(recorded_start):
                raise ValueError("Missing or invalid exact process identity")
            process = psutil.Process(pid)
            started = process.create_time()
            executable = Path(process.exe()).resolve()
            # A reused PID must not cause a command-line read of an unrelated app.
            if executable != BACKEND.resolve() or abs(started - recorded_start) >= 0.01 or not process.is_running():
                raise ValueError("Recorded PID no longer identifies the expected backend process")
            argv = process.cmdline()
            if argv.count("--max-battles") > 1 or argv.count("--strategy") != 1:
                raise ValueError("Ambiguous battle limit or strategy arguments")
            maximum = (
                int(argv[argv.index("--max-battles") + 1])
                if "--max-battles" in argv
                else 0
            )
            expected_component = (
                "watch_cn_1v1.py" if role == "watchdog" else "run_cn_1v1.py"
            )
            result[role] = {
                "pid": pid,
                "exe": process.exe(),
                "cmdline": argv,
                "created_at": started,
                "max_battles": maximum,
                "passed": len(argv) > 2 and argv[1:3] == ["--component", expected_component]
                and argv[argv.index("--strategy") + 1] == "random" and maximum == 0,
            }
        except (psutil.Error, ValueError, TypeError, IndexError) as error:
            result[role] = {"pid": pid, "passed": False, "error": str(error)}
    return result


def path_key(path):
    return str(Path(path).resolve()).casefold()


def manifest_identity(manifest, rows):
    hashes = manifest.get("sha256", {})
    hashes = hashes if isinstance(hashes, dict) else {}
    normalized = {path_key(path): value for path, value in hashes.items()}
    sources = {}
    for name in RUNTIME_SOURCES:
        source = ROOT / "py-clash-bot/pyclashbot" / name
        packaged = BACKEND.parent / "source/pyclashbot" / name
        expected = digest(source) if source.is_file() else None
        recorded = normalized.get(path_key(packaged))
        sources[name] = {"source_sha256": expected, "recorded_sha256": recorded, "passed": bool(expected) and packaged.is_file() and digest(packaged) == expected == recorded}
    recorded_files = {}
    for path, value in hashes.items():
        actual = Path(path).resolve()
        recorded_files[path] = actual.is_relative_to(BACKEND.parent.resolve()) and actual.is_file() and digest(actual) == value
    asset_rows = {name: value for name, value in hashes.items() if name.endswith((".png", ".json"))}
    asset_hash = hashlib.sha256(json.dumps(asset_rows, sort_keys=True).encode()).hexdigest()
    experiment = manifest.get("experiment", {})
    environment = manifest.get("environment", {})
    experiment = experiment if isinstance(experiment, dict) else {}
    environment = environment if isinstance(environment, dict) else {}
    env_hash = hashlib.sha256(json.dumps({k: v for k, v in environment.items() if k != "sha256"}, sort_keys=True).encode()).hexdigest()
    strategy_hash = normalized.get(path_key(BACKEND.parent / "source/pyclashbot/bot/random_deck_strategy.py"))
    gates = {
        "current_sources_equal_frozen_and_manifest": all(row["passed"] for row in sources.values()),
        "all_recorded_files_equal_package": bool(recorded_files) and all(recorded_files.values()),
        "asset_identity_recomputed": bool(asset_rows) and experiment.get("asset_hash") == asset_hash,
        "strategy_identity_matches_source": bool(strategy_hash) and experiment.get("strategy_hash") == strategy_hash,
        "environment_identity_recomputed": experiment.get("environment_hash") == manifest.get("environment_hash") == environment.get("sha256") == env_hash,
        "event_identities_match_manifest": bool(experiment) and bool(rows) and all(row.get("experiment") == experiment for row in rows),
    }
    return {"passed": all(gates.values()), "gates": gates, "sources": sources, "recorded_files": recorded_files, "recomputed_asset_hash": asset_hash}, normalized


def cycle_evidence(rows, baseline_completed):
    stages = ("battle_started", "battle_finished", "result_committed", "returned_lobby", "mastery_checked", "cycle_complete")
    completed = []
    for battle in sorted({row.get("battle") for row in rows if type(row.get("battle")) is int and row["battle"] > baseline_completed}):
        indices, cursor = {}, -1
        for stage in stages:
            index = next((i for i, row in enumerate(rows) if i > cursor and row.get("battle") == battle and row.get("event") == stage), None)
            if index is None:
                break
            indices[stage], cursor = index, index
        sequential = not completed or indices.get("battle_started", -1) > completed[-1]["indices"]["cycle_complete"]
        if len(indices) == len(stages) and sequential and not rows[indices["cycle_complete"]].get("resumed", False):
            completed.append({"battle": battle, "indices": indices})
    active = rows[-1].get("battle") if rows else None
    return completed, active


def frame_evidence(row, classify=False):
    evidence = row.get("evidence", {})
    path = Path(evidence.get("path", "")).resolve()
    result = {"path": str(path), "passed": False}
    if not path.is_relative_to((ROOT / "work/random-mastery").resolve()) or not path.is_file():
        return result
    result["passed"] = digest(path) == evidence.get("sha256")
    if classify and result["passed"]:
        import cv2  # noqa: PLC0415 - only local evidence, never a device controller

        sys.dont_write_bytecode = True
        sys.path.insert(0, str(ROOT / "py-clash-bot"))
        from pyclashbot.bot.cn_1v1_loop import ChineseVision  # noqa: PLC0415

        image = cv2.imread(str(path))
        result["kind"] = ChineseVision().classify(image)[0] if image is not None else None
        result["passed"] = result["kind"] == "battle"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", action="store_true")
    args = parser.parse_args()
    baseline_path = TASK / "infinite-runtime-baseline.json"
    current = snapshot()
    trace = ROOT / "outputs/cn-random-mastery.jsonl"
    if args.baseline:
        if baseline_path.exists():
            raise FileExistsError("Preserve the recorded runtime baseline")
        if current["status"]["state"] not in {"stopped", "paused"}:
            raise RuntimeError("Baseline must be recorded while the bot is stopped")
        current.update(
            trace_offset=trace.stat().st_size,
            reports=reports(),
            frontend_hashes=protected_frontend(),
        )
        save(baseline_path, current)
        print(
            json.dumps(
                {
                    "baseline": str(baseline_path),
                    "completed": current["checkpoint"]["completed"],
                }
            )
        )
        return
    baseline = read(baseline_path)
    with trace.open("rb") as stream:
        stream.seek(baseline["trace_offset"])
        payload = stream.read()
    # The live writer can be in the middle of its next line. Do not parse an
    # unfinished tail or hide malformed complete records.
    lines = payload.splitlines(keepends=True)
    partial_tail = len(lines.pop()) if lines and not lines[-1].endswith(b"\n") else 0
    rows, parse_errors = [], []
    for index, line in enumerate(lines):
        if line.strip():
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("A completed trace row must be a JSON object")
                rows.append(row)
            except ValueError as error:
                parse_errors.append({"line": index, "error": str(error)})
    session = current["status"]["session"]
    rows = [row for row in rows if row.get("session") == session]
    starts = [row for row in rows if row.get("event") == "started"]
    manifest_path = Path(current["status"]["evidence_dir"]) / "manifest.json"
    expected_session_dir = (ROOT / "work/random-mastery" / session).resolve()
    manifest = read(manifest_path) if manifest_path.is_file() and manifest_path.parent.resolve() == expected_session_dir else {}
    identity, normalized_hashes = manifest_identity(manifest, rows)
    assets = {}
    for folder in ("cn_daily_gift", "cn_pages"):
        source = ROOT / "py-clash-bot/pyclashbot/detection/reference_images" / folder
        for path in sorted(source.rglob("*")):
            if path.is_file() and path.suffix.lower() in {".png", ".json"}:
                packaged = (
                    BACKEND.parent
                    / "pyclashbot/detection/reference_images"
                    / folder
                    / path.relative_to(source)
                )
                assets[str(path.relative_to(source.parent))] = {
                    "sha256": digest(path),
                    "recorded_sha256": normalized_hashes.get(path_key(packaged)),
                    "passed": packaged.is_file()
                    and digest(path) == digest(packaged)
                    and normalized_hashes.get(path_key(packaged)) == digest(path),
                }
    processes = process_evidence(current["process_record"])
    cp, before = current["checkpoint"], baseline["checkpoint"]
    complete_cycles, _ = cycle_evidence(rows, before["completed"])
    active_battle = cp["completed"] + 1
    last_cycle_index = complete_cycles[-1]["indices"]["cycle_complete"] if complete_cycles else -1
    active_starts = [i for i, row in enumerate(rows) if i > last_cycle_index and row.get("event") == "battle_started" and row.get("battle") == active_battle]
    active_frames = [row for i, row in enumerate(rows) if active_starts and i >= active_starts[-1] and row.get("battle") == active_battle and row.get("event") in {"battle_started", "battle_observed"}]
    next_frame = frame_evidence(active_frames[-1], classify=True) if active_frames else {"passed": False}
    frame_age = (
        datetime.now(SHANGHAI) - datetime.strptime(active_frames[-1]["time"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=SHANGHAI)
    ).total_seconds() if active_frames else None
    closure_frames = [frame_evidence(rows[cycle["indices"][event]]) for cycle in complete_cycles for event in ("battle_finished", "returned_lobby", "mastery_checked")]
    report_after = reports()
    report_delta = {
        "added": sorted(set(report_after) - set(baseline["reports"])),
        "removed": sorted(set(baseline["reports"]) - set(report_after)),
        "changed": sorted(path for path in set(report_after) & set(baseline["reports"]) if report_after[path] != baseline["reports"][path]),
    }
    state_age = (datetime.now(SHANGHAI) - datetime.strptime(current["status"]["updated_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=SHANGHAI)).total_seconds()
    gates = {
        "trace_valid": not parse_errors and trace.stat().st_size >= baseline["trace_offset"],
        "new_backend_frontend": Path(current["frontend"]["backend_path"]).resolve()
        == BACKEND.resolve() and current["frontend"].get("framework") == "WPF" and current["frontend"].get("state") == "running",
        "same_wpf_and_shortcut": protected_frontend() == baseline["frontend_hashes"],
        "watchdog_and_runner_new_backend": all(
            row["passed"] for row in processes.values()
        ),
        "processes_started_after_baseline": all(row.get("created_at", 0) >= datetime.fromisoformat(baseline["time"]).timestamp() for row in processes.values()),
        "infinite_started_event": bool(starts) and starts[-1].get("max_battles") == 0,
        "new_policy": manifest.get("policy") == POLICY
        and bool(rows)
        and all(row.get("policy") == POLICY for row in rows),
        "runtime_manifest_identity": identity["passed"],
        "current_page_assets_recorded": bool(assets)
        and all(row["passed"] for row in assets.values()),
        "classic_mode_verified": any(
            row.get("event") == "classic_navigation_verified" for row in rows
        ),
        "two_complete_cycles": len(complete_cycles) >= 2 and bool(closure_frames) and all(row["passed"] for row in closure_frames)
        and cp["closed_loops"] >= before["closed_loops"] + 2
        and cp["completed"] >= before["completed"] + 2
        and cp["completed"] - before["completed"] == cp["closed_loops"] - before["closed_loops"],
        "next_battle_active": bool(active_starts) and next_frame["passed"]
        and frame_age is not None and 0 <= frame_age <= 30
        and current["status"]["state"] == "battle"
        and current["process_record"].get("phase") == "running" and current["process_record"].get("strategy") == "random"
        and current["status"].get("pid") == current["process_record"].get("runner_pid")
        and current["status"].get("mode") == "classic_1v1" and 0 <= state_age <= 30
        and current["status"].get("completed") == cp["completed"] and current["status"].get("closed_loops") == cp["closed_loops"]
        and not cp["pending_mastery"] and not cp["pending_claim_all"] and cp["pending_battle"] is True,
        "original_reports_unchanged_no_new_reports": not any(report_delta.values()),
        "drain_request_archived": not (ROOT / "work/random-mastery/DRAIN").exists(),
        "no_pause_events": not any(
            row.get("event") in {"paused", "finite_complete"} for row in rows
        ),
    }
    result = {
        "schema": "clash-infinite-runtime-acceptance-v1",
        "snapshot": current,
        "gates": gates,
        "passed": all(gates.values()),
        "processes": processes,
        "manifest": str(manifest_path),
        "manifest_identity": identity,
        "complete_cycle_chains": complete_cycles,
        "closure_frame_hashes": closure_frames,
        "active_battle_frame": next_frame,
        "active_battle_frame_age_seconds": frame_age,
        "state_age_seconds": state_age,
        "report_delta": report_delta,
        "current_report_hashes": report_after,
        "trace_parse_errors": parse_errors,
        "unfinished_trace_tail_bytes": partial_tail,
        "assets": assets,
        "events": [
            row
            for row in rows
            if row.get("event")
            in {
                "started",
                "classic_navigation_verified",
                "battle_started",
                "battle_finished",
                "battle_observed",
                "result_committed",
                "returned_lobby",
                "mastery_checked",
                "cycle_complete",
                "paused",
                "finite_complete",
            }
        ],
        "game_input_sent": False,
        "robot_start_or_stop_requested": False,
    }
    save(TASK / "infinite-runtime-verification.json", result)
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "gates": gates,
                "session": session,
                "completed": cp["completed"],
                "closed_loops": cp["closed_loops"],
            }
        )
    )
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
