"""Exercise the actual loop on the current free reward, stopping at the lobby."""

import json
import logging
from pathlib import Path
import time

import cv2

from pyclashbot.bot.cn_1v1_loop import ChineseOneVOneLoop

ROOT = Path(__file__).resolve().parents[1]
logging.basicConfig(level=logging.INFO)
runner = ChineseOneVOneLoop(
    str(ROOT.parent / "tool_runtimes/android-platform-tools/platform-tools/adb.exe"),
    "127.0.0.1:21503", logging.getLogger("reward-live-validation"),
)
# The previous probe reached this puzzle reveal by opening the actual reward.
# Resume that known context; the production loop retains it automatically.
runner.reward_pending = True
rows = []
deadline = time.monotonic() + 45
reached_lobby = False
while time.monotonic() < deadline:
    frame = runner.device.screenshot()
    kind, _ = runner.vision.classify(frame)
    record = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": kind,
              "evidence": runner._save_evidence("reward-return-validation", frame)}
    rows.append(record)
    if kind == "lobby":
        reached_lobby = True
        break
    if kind not in {"reward", "unknown"}:
        break
    runner._step(frame)
    time.sleep(0.5)
result = {"reached_lobby": reached_lobby, "reward_taps": runner.reward_taps,
          "session": runner.validation_dir.name, "frames": rows,
          "limitation": "Actual paused reward was resumed with the loop; not an uninterrupted new win-to-next-match run."}
output = ROOT / "outputs/hog-v3-reward-return.json"
output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"reached_lobby": reached_lobby, "reward_taps": runner.reward_taps,
                  "report": str(output)}, ensure_ascii=False))
raise SystemExit(0 if reached_lobby else 1)
