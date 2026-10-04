"""Capture the already attached game's screen for navigation calibration."""
import argparse
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
ADB = Path(r"D:\codex\CodexWork\tool_runtimes\android-platform-tools\platform-tools\adb.exe")

parser = argparse.ArgumentParser()
parser.add_argument("name")
args = parser.parse_args()
if not args.name.replace("_", "").replace("-", "").isalnum():
    raise ValueError("simple page name required")
raw = subprocess.run([str(ADB), "-s", "127.0.0.1:21503", "exec-out", "screencap", "-p"], capture_output=True, check=True, timeout=15).stdout
frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
if frame is None or frame.shape != (633, 419, 3):
    raise ValueError("unexpected emulator resolution")
path = ROOT / "pages" / f"{args.name}.png"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_bytes(raw)
print(json.dumps({"name":args.name, "path":str(path), "shape":list(frame.shape)}))
