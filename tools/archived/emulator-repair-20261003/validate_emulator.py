"""Collect bounded, read-only MEmu runtime evidence after a repair."""

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(r"D:\codex\CodexWork\clash")
sys.path.insert(0, str(ROOT / "py-clash-bot"))
from pyclashbot.bot.cn_1v1_loop import ChineseVision  # noqa: E402

ADB = Path(r"D:\codex\CodexWork\tool_runtimes\android-platform-tools\platform-tools\adb.exe")
MEMUC = ROOT / "work/downloads/Microvirt/MEmu/memuc.exe"
SERIAL = "127.0.0.1:21503"
WORK = ROOT / "work/emulator-repair-20261003"


def run(command, timeout=15):
    started = time.monotonic()
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout)
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout.decode("utf-8", errors="replace").strip(),
            "stderr": result.stderr.decode("utf-8", errors="replace").strip(),
            "duration_seconds": round(time.monotonic() - started, 3),
        }
    except subprocess.TimeoutExpired:
        return {"exit_code": None, "timeout": True, "duration_seconds": round(time.monotonic() - started, 3)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="runtime-after")
    parser.add_argument("--samples", type=int, default=5)
    args = parser.parse_args()
    if not 2 <= args.samples <= 10 or not args.name.replace("-", "").isalnum():
        parser.error("Use 2-10 samples and an alphanumeric name.")
    result = {"recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"), "timezone": "Asia/Shanghai"}
    result["device"] = run([str(ADB), "-s", SERIAL, "get-state"])
    result["boot_completed"] = run([str(ADB), "-s", SERIAL, "shell", "getprop", "sys.boot_completed"])
    result["resolution"] = run([str(ADB), "-s", SERIAL, "shell", "wm", "size"])
    result["density"] = run([str(ADB), "-s", SERIAL, "shell", "wm", "density"])
    result["configuration"] = {
        key: run([str(MEMUC), "getconfigex", "-i", "0", key])
        for key in ("cpus", "memory", "graphics_render_mode", "custom_resolution", "fps")
    }
    frames = []
    vision = ChineseVision()
    if result["device"].get("stdout") == "device":
        for index in range(args.samples):
            started = time.monotonic()
            capture = subprocess.run([str(ADB), "-s", SERIAL, "exec-out", "screencap", "-p"],
                                     capture_output=True, timeout=20)
            frame = cv2.imdecode(np.frombuffer(capture.stdout, np.uint8), cv2.IMREAD_COLOR)
            row = {"index": index, "exit_code": capture.returncode,
                   "duration_seconds": round(time.monotonic() - started, 3), "png_bytes": len(capture.stdout)}
            if frame is not None:
                path = WORK / f"{args.name}-{index:02d}.png"
                path.write_bytes(capture.stdout)
                row.update({"shape": list(frame.shape), "kind": vision.classify(frame)[0],
                            "pixel_standard_deviation": round(float(np.std(frame)), 3),
                            "visible_content": float(np.std(frame)) >= 2,
                            "sha256": hashlib.sha256(capture.stdout).hexdigest(), "path": str(path)})
            frames.append(row)
            if index + 1 < args.samples:
                time.sleep(1)
        result["domestic_network"] = run(
            [str(ADB), "-s", SERIAL, "shell",
             "ping -c 5 -W 2 223.5.5.5; curl --connect-timeout 5 --max-time 10 -s -o /dev/null -w 'HTTP_STATUS=%{http_code} TOTAL_SECONDS=%{time_total}' https://www.baidu.com"], 25)
    result["frames"] = frames
    result["distinct_frames"] = len({row["sha256"] for row in frames if "sha256" in row})
    if frames:
        result["screenshot_median_seconds"] = round(statistics.median(row["duration_seconds"] for row in frames), 3)
    result["checks"] = {
        "adb_online": result["device"].get("stdout") == "device",
        "android_booted": result["boot_completed"].get("stdout") == "1",
        "original_resolution": "419x633" in result["resolution"].get("stdout", ""),
        "all_frames_decoded": len(frames) == args.samples and all("shape" in row for row in frames),
        "all_frames_visible": len(frames) == args.samples and all(row.get("visible_content", False) for row in frames),
        "frames_changing": result["distinct_frames"] > 1,
    }
    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK / f"{args.name}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"path": str(path), "checks": result["checks"],
                      "distinct_frames": result["distinct_frames"],
                      "screenshot_median_seconds": result.get("screenshot_median_seconds")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
