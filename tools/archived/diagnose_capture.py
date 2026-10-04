import subprocess
import time

import cv2
import numpy as np

ADB = r"D:\codex\CodexWork\tool_runtimes\android-platform-tools\platform-tools\adb.exe"
SERIAL = "127.0.0.1:21503"

for label, command in (
    ("exec-out", [ADB, "-s", SERIAL, "exec-out", "screencap", "-p"]),
    ("shell", [ADB, "-s", SERIAL, "shell", "screencap", "-p"]),
    ("write-device", [ADB, "-s", SERIAL, "shell", "screencap", "-p", "/sdcard/capture.png"]),
):
    started = time.monotonic()
    try:
        result = subprocess.run(command, capture_output=True, timeout=10, check=False)
        image = cv2.imdecode(np.frombuffer(result.stdout, dtype=np.uint8), cv2.IMREAD_COLOR)
        print(label, "rc", result.returncode, "sec", round(time.monotonic() - started, 2),
              "bytes", len(result.stdout), "shape", None if image is None else image.shape,
              "stderr", result.stderr[:100])
    except subprocess.TimeoutExpired:
        print(label, "timeout", round(time.monotonic() - started, 2))
