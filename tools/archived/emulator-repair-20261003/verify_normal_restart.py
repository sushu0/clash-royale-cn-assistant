"""Verify a graceful MEmu stop, native GUI cold start, and original game lobby."""

import json
import logging
import subprocess
import time
from pathlib import Path

import cv2
import psutil

from pyclashbot.bot.cn_1v1_loop import ChineseVision, TimedAdbController, _LogAdapter
from pyclashbot.emulators.base import CLASH_ROYALE_PACKAGE

ROOT = Path(r"D:\codex\CodexWork\clash")
WORK = ROOT / "work/emulator-repair-20261003"
MEMUC = ROOT / "work/downloads/Microvirt/MEmu/memuc.exe"
ADB = Path(r"D:\codex\CodexWork\tool_runtimes\android-platform-tools\platform-tools\adb.exe")
SERIAL = "127.0.0.1:21503"
CHECKPOINT = ROOT / "work/random-mastery/checkpoint.json"


def command(args, timeout=8):
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout)
        return {"exit_code": result.returncode, "stdout": result.stdout.decode("utf-8", errors="replace").strip(),
                "stderr": result.stderr.decode("utf-8", errors="replace").strip()}
    except subprocess.TimeoutExpired:
        return {"exit_code": None, "timeout": True}


def emu_processes():
    return [p.info["pid"] for p in psutil.process_iter(["pid", "name"])
            if p.info["name"] in {"MEmu.exe", "MEmuHeadless.exe"}]


def main():
    checkpoint_before = CHECKPOINT.read_bytes()
    report = {"started_at": time.strftime("%Y-%m-%d %H:%M:%S"), "timezone": "Asia/Shanghai", "checks": {}}
    try:
        started = time.monotonic()
        report["stop_command"] = command([str(MEMUC), "stop", "-i", "0"], 20)
        deadline = time.monotonic() + 15
        while emu_processes() and time.monotonic() < deadline:
            time.sleep(0.5)
        report["stop_seconds"] = round(time.monotonic() - started, 3)
        report["checks"]["normal_stop"] = not emu_processes() and "SUCCESS" in report["stop_command"].get("stdout", "")
        if not report["checks"]["normal_stop"]:
            raise RuntimeError("Graceful stop did not complete; no force-stop or cold launch attempted.")
        listed = command([str(MEMUC), "listvms"])
        rows = [row.split(",", 1) for row in listed.get("stdout", "").splitlines() if row.strip()]
        if listed.get("exit_code") != 0 or len(rows) != 1 or rows[0][0] != "0":
            raise RuntimeError("Sole existing VM 0 could not be verified.")
        launch_started = time.monotonic()
        gui = subprocess.Popen([str(MEMUC.with_name("MEmu.exe"))], cwd=MEMUC.parent,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        report["launch_pid"] = gui.pid
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            state = command([str(ADB), "-s", SERIAL, "get-state"], 5)
            if state.get("stdout") == "device":
                boot = command([str(ADB), "-s", SERIAL, "shell", "getprop", "sys.boot_completed"], 5)
                if boot.get("stdout") == "1":
                    break
            else:
                command([str(ADB), "connect", SERIAL], 5)
            time.sleep(1)
        else:
            raise RuntimeError("Android did not boot within 90 seconds.")
        report["boot_seconds"] = round(time.monotonic() - launch_started, 3)
        report["checks"]["android_restarted"] = True
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            packages = command([str(ADB), "-s", SERIAL, "shell", "pm", "list", "packages", CLASH_ROYALE_PACKAGE], 5)
            if f"package:{CLASH_ROYALE_PACKAGE}" in packages.get("stdout", "").splitlines():
                break
            time.sleep(1)
        else:
            raise RuntimeError("Original game package did not become ready.")
        report["checks"]["original_game_present"] = True
        report["game_launch"] = command([str(ADB), "-s", SERIAL, "shell", "monkey", "-p", CLASH_ROYALE_PACKAGE,
                                          "-c", "android.intent.category.LAUNCHER", "1"], 15)
        TimedAdbController.adb_path = str(ADB)
        device = TimedAdbController(_LogAdapter(logging.getLogger("normal-restart")), device_serial=SERIAL)
        vision = ChineseVision()
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            frame = device.screenshot()
            if vision.classify(frame)[0] == "lobby" and device.foreground_package() == CLASH_ROYALE_PACKAGE:
                path = WORK / "post-restart-lobby.png"
                cv2.imwrite(str(path), frame)
                report["lobby_evidence"] = str(path)
                report["checks"]["lobby_restored"] = True
                break
            time.sleep(1)
        else:
            raise RuntimeError("Original game lobby was not observed after cold start.")
        report["checks"]["checkpoint_unchanged"] = CHECKPOINT.read_bytes() == checkpoint_before
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        report["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        path = WORK / "post-reboot-normal-restart.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
