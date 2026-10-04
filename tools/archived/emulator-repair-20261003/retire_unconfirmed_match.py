"""One-off maintenance of the specific unconfirmed pre-reboot match attempt."""

import argparse
import hashlib
import json
import logging
import os
import time
import uuid
from pathlib import Path

import msvcrt

from pyclashbot.bot.cn_1v1_loop import ChineseVision, TimedAdbController, _LogAdapter
from pyclashbot.emulators.base import CLASH_ROYALE_PACKAGE

ROOT = Path(r"D:\codex\CodexWork\clash")
WORK = ROOT / "work/emulator-repair-20261003"
CHECKPOINT = ROOT / "work/random-mastery/checkpoint.json"
TRACE = ROOT / "outputs/cn-random-mastery.jsonl"
STATUS = ROOT / "outputs/random-mastery-live-status.json"
ADB = r"D:\codex\CodexWork\tool_runtimes\android-platform-tools\platform-tools\adb.exe"
EXPECTED_SESSION = "20261003-155047"
EXPECTED_NUMBERS = {"completed": 912, "generated": 920, "closed_loops": 912, "total_claimed": 128}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    lock = (ROOT / "work/cn-runner.lock").open("r+b")
    lock.seek(0)
    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    try:
        before_bytes = CHECKPOINT.read_bytes()
        before = json.loads(before_bytes)
        if any(before.get(key) != value for key, value in EXPECTED_NUMBERS.items()):
            raise RuntimeError("Historical counters changed; maintenance refused.")
        if not before.get("pending_battle") or before.get("pending_mastery") or before.get("pending_claim_all"):
            raise RuntimeError("Expected isolated pending match was not found.")
        trace_size = TRACE.stat().st_size
        with TRACE.open("rb") as stream:
            stream.seek(max(0, trace_size - 2 * 1024**2))
            tail = stream.read()
        events = []
        for line in tail.splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
        candidates = [i for i, row in enumerate(events)
                      if row.get("event") == "match_requested" and row.get("session") == EXPECTED_SESSION
                      and row.get("generation") == 920 and row.get("battle") == 913]
        if len(candidates) != 1:
            raise RuntimeError("Specific match request could not be verified.")
        subsequent = events[candidates[0]:]
        if any(row.get("event") in {"battle_started", "battle_resumed", "battle_finished"} for row in subsequent):
            raise RuntimeError("A battle was observed after this request; maintenance refused.")
        if not any(row.get("event") == "paused" and row.get("session") == EXPECTED_SESSION for row in subsequent):
            raise RuntimeError("Old matching timeout was not verified.")
        TimedAdbController.adb_path = ADB
        device = TimedAdbController(_LogAdapter(logging.getLogger("maintenance")), device_serial="127.0.0.1:21503")
        vision = ChineseVision()
        maintenance_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        evidence_dir = WORK / f"maintenance-{maintenance_id}"
        evidence_dir.mkdir()
        frames = []
        for index in range(2):
            frame = device.screenshot()
            kind = vision.classify(frame)[0]
            if kind != "lobby" or device.foreground_package() != CLASH_ROYALE_PACKAGE:
                raise RuntimeError(f"Stable existing game lobby required; observed {kind}.")
            import cv2
            ok, encoded = cv2.imencode(".png", frame)
            if not ok:
                raise RuntimeError("Could not preserve live lobby evidence.")
            data = encoded.tobytes()
            image_path = evidence_dir / f"lobby-{index}.png"
            image_path.write_bytes(data)
            frames.append({"kind": kind, "path": str(image_path), "sha256": digest(data)})
            if index == 0:
                time.sleep(2)
        after = {**before, "pending_battle": False}
        after_bytes = json.dumps(after, ensure_ascii=False, indent=2).encode("utf-8")
        changed = [key for key in before if before[key] != after[key]]
        if changed != ["pending_battle"]:
            raise RuntimeError("Unexpected checkpoint difference.")
        record = {
            "event": "maintenance_abandoned_match_attempt", "maintenance_id": maintenance_id,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"), "timezone": "Asia/Shanghai",
            "abandoned_session": EXPECTED_SESSION, "abandoned_generation": 920, "requested_battle": 913,
            "outcome": "UNKNOWN", "confirmed_completed": False,
            "reason": "Pre-reboot matching request never confirmed battle start; stable lobby now observed.",
            "before_sha256": digest(before_bytes), "after_sha256": digest(after_bytes),
            "changed_fields": changed, "counters_preserved": EXPECTED_NUMBERS,
            "trace_bytes_before": trace_size, "trace_tail_sha256": digest(tail),
            "lobby_evidence": frames, "applied": False,
        }
        (evidence_dir / "checkpoint.before.json").write_bytes(before_bytes)
        (evidence_dir / "status.before.json").write_bytes(STATUS.read_bytes())
        record_path = evidence_dir / "maintenance.json"
        record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.apply:
            if CHECKPOINT.read_bytes() != before_bytes or TRACE.stat().st_size != trace_size:
                raise RuntimeError("Checkpoint or trace changed during verification; maintenance refused.")
            temporary = CHECKPOINT.with_name("checkpoint.maintenance.tmp")
            temporary.write_bytes(after_bytes)
            os.replace(temporary, CHECKPOINT)
            record["applied"] = True
            with TRACE.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"record": str(record_path), "applied": record["applied"],
                          "changed_fields": changed, "counters_preserved": EXPECTED_NUMBERS}, ensure_ascii=False))
    finally:
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        lock.close()


if __name__ == "__main__":
    main()
