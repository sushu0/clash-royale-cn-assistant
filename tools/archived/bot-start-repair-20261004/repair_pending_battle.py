"""Explicit maintenance for an interrupted pending battle confirmed at the lobby."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from pyclashbot.bot.cn_1v1_loop import ChineseVision
from pyclashbot.bot.cn_random_mastery_loop import RandomMasteryLoop
from pyclashbot.utils.persistence import atomic_write_bytes, atomic_write_json
from pyclashbot.utils.process_ownership import ExclusiveFileLock, device_lock_path
from pyclashbot.utils.runtime_config import load_runtime_config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    runtime = load_runtime_config()
    root = runtime.data_root
    folder = Path(__file__).resolve().parent
    checkpoint_path = root / "work/random-mastery/checkpoint.json"
    outbox_path = root / "work/random-mastery/pending-result.json"
    vision = ChineseVision()
    with (
        ExclusiveFileLock(root / "work/bot-processes.lock"),
        ExclusiveFileLock(device_lock_path()),
    ):
        original = checkpoint_path.read_bytes()
        checkpoint = json.loads(original)
        assert RandomMasteryLoop._valid_checkpoint(checkpoint), "Invalid checkpoint"
        assert checkpoint["pending_battle"] is True, "No interrupted battle to repair"
        assert not checkpoint["pending_mastery"] and not checkpoint["pending_claim_all"]
        assert checkpoint["closed_loops"] == checkpoint["completed"]
        outbox = json.loads(outbox_path.read_bytes())
        assert outbox["committed"] is True, "Uncommitted result must be replayed first"
        assert outbox["row"]["finished_battle"] == checkpoint["completed"]
        result_evidence = outbox["row"]["evidence"]
        assert hashlib.sha256(Path(result_evidence["path"]).read_bytes()).hexdigest() == result_evidence["sha256"]
        observed = []
        for index in range(3):
            shot = subprocess.run(
                [str(runtime.adb), "-s", runtime.serial, "exec-out", "screencap", "-p"],
                capture_output=True,
                timeout=10,
                check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            frame = cv2.imdecode(np.frombuffer(shot.stdout, dtype=np.uint8), cv2.IMREAD_COLOR)
            assert frame is not None, "ADB screenshot could not be decoded"
            kind, _ = vision.classify(frame)
            path = folder / f"lobby-confirmed-{index + 1}.png"
            atomic_write_bytes(path, shot.stdout)
            observed.append({"kind": kind, "shape": list(frame.shape), "path": str(path)})
            assert kind == "lobby", f"Battle may still be active: {kind}"
            if index < 2:
                time.sleep(1)
        assert checkpoint_path.read_bytes() == original, "Checkpoint changed during maintenance"
        report = {
            "captured_at": datetime.now().astimezone().isoformat(),
            "action": "explicit_user_authorized_interrupted_battle_repair",
            "applied": args.apply,
            "reason": "pending_battle remained true after game returned to verified lobby; no result evidence for interrupted battle",
            "interrupted_battle": checkpoint["completed"] + 1,
            "interrupted_generation": checkpoint["generated"],
            "interrupted_outcome": "unrecorded; excluded from completed win/loss statistics",
            "before": checkpoint,
            "observations": observed,
            "locks": ["bot-processes.lock", "cn-runner.lock"],
            "backup_dir": str(folder),
            "history_bytes_before": (root / "outputs/cn-random-mastery.jsonl").stat().st_size,
            "rewards_bytes_before": (root / "outputs/cn-mastery-rewards.jsonl").stat().st_size,
        }
        if args.apply:
            for path in (
                checkpoint_path,
                checkpoint_path.with_suffix(".json.bak"),
                outbox_path,
                root / "work/bot-processes.json",
                root / "outputs/random-mastery-live-status.json",
            ):
                if path.is_file():
                    atomic_write_bytes(folder / f"{path.name}.before", path.read_bytes())
            updated = dict(checkpoint, pending_battle=False)
            assert {key for key in checkpoint if checkpoint[key] != updated[key]} == {"pending_battle"}
            report["after"] = updated
            atomic_write_json(folder / "repair-intent.json", report)
            atomic_write_json(checkpoint_path, updated, backup=True, validator=RandomMasteryLoop._valid_checkpoint)
            assert json.loads(checkpoint_path.read_bytes()) == updated
            assert (root / "outputs/cn-random-mastery.jsonl").stat().st_size == report["history_bytes_before"]
            assert (root / "outputs/cn-mastery-rewards.jsonl").stat().st_size == report["rewards_bytes_before"]
        atomic_write_json(folder / ("repair-applied.json" if args.apply else "preflight.json"), report)
        print(json.dumps({"applied": args.apply, "observations": observed, "completed": checkpoint["completed"], "changed_keys": ["pending_battle"] if args.apply else []}, ensure_ascii=False))


if __name__ == "__main__":
    main()
