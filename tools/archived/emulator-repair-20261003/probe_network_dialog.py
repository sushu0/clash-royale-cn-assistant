"""Briefly disconnect only MEmu, preserving screenshots and restoring connectivity."""

import base64
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(r"D:\codex\CodexWork\clash")
WORK = ROOT / "work/emulator-repair-20261003"
MEMUC = ROOT / "work/downloads/Microvirt/MEmu/memuc.exe"


def main():
    rows = []
    try:
        disconnected = subprocess.run([str(MEMUC), "disconnect", "-i", "0"], capture_output=True, timeout=10)
        if disconnected.returncode:
            raise RuntimeError("MEmu disconnect command failed")
        for index in range(8):
            time.sleep(4)
            frame = subprocess.run([str(MEMUC), "-i", "0", "execcmd", "screencap -p | base64"],
                                   capture_output=True, timeout=8)
            row = {"index": index, "seconds": 4 * (index + 1), "exit_code": frame.returncode}
            try:
                pixels = base64.b64decode(b"".join(frame.stdout.split()), validate=True)
            except ValueError:
                pixels = b""
            if pixels.startswith(bytes([137, 80, 78, 71, 13, 10, 26, 10])):
                path = WORK / f"network-dialog-{index:02d}.png"
                path.write_bytes(pixels)
                row["path"] = str(path)
            rows.append(row)
    finally:
        restored = subprocess.run([str(MEMUC), "connect", "-i", "0"], capture_output=True, timeout=10)
        rows.append({"network_restored": restored.returncode == 0,
                     "command_stdout": restored.stdout.decode("utf-8", errors="replace").strip()})
        (WORK / "network-fault-probe.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(json.dumps(rows))


if __name__ == "__main__":
    main()
