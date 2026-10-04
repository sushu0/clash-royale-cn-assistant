"""Measure existing decision behavior and offline perception without sending inputs."""
import json
import statistics
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from pyclashbot.bot.cn_1v1_loop import ChineseVision, TimedAdbController, _LogAdapter
from pyclashbot.bot.random_deck_strategy import RandomDeckStrategy
from pyclashbot.detection.cn_battle_cues import read_cn_battle_cues
from pyclashbot.detection.cn_random_hand import identify_random_hand
import logging

ROOT = Path(r"D:\codex\CodexWork\clash")
live = json.loads((ROOT / "outputs/random-mastery-live-status.json").read_text(encoding="utf-8"))
rows = [json.loads(x) for x in (ROOT / "outputs/cn-random-mastery.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
rows = [r for r in rows if r.get("battle", 0) >= live["completed"] - 19
        and (r.get("strategy_version") == "random-rules-v1.1-20261001"
             or r.get("policy") == "random-mastery-role-policy-v16-20261001")]
plays = [r for r in rows if r["event"] == "play"]
intervals, prior = [], {}
for row in plays:
    stamp = datetime.strptime(row["time"], "%Y-%m-%d %H:%M:%S").timestamp()
    key = (row["session"], row["battle"])
    if key in prior:
        intervals.append(stamp - prior[key])
    prior[key] = stamp
observed = [r for r in rows if r["event"] == "strategy_observe"]
failed = [{k: r.get(k) for k in ("battle", "card_hint", "category", "elixir", "after_elixir", "portrait_change", "time")} for r in plays if not r["confirmed"]]
vision = ChineseVision()
frames = [cv2.imread(str(p)) for p in Path(live["evidence_dir"]).glob("recent-*.png")]
frames = [f for f in frames if f is not None and vision.classify(f)[0] == "battle"][:12]
timings = {}
for name, fn in (("state", vision.classify), ("hand", identify_random_hand),
                 ("cues", lambda f: read_cn_battle_cues(f, include_567=True))):
    fn(frames[0])
    values = []
    for f in frames:
        start = time.perf_counter()
        fn(f)
        values.append((time.perf_counter() - start)*1000)
    timings[name] = {"median_ms": round(statistics.median(values), 2), "p95_ms": round(float(np.percentile(values, 95)), 2)}
TimedAdbController.adb_path = r"D:\codex\CodexWork\tool_runtimes\android-platform-tools\platform-tools\adb.exe"
device = TimedAdbController(_LogAdapter(logging.getLogger("benchmark")), device_serial="127.0.0.1:21503")
values = []
for _ in range(3):
    start = time.perf_counter()
    device.screenshot()
    values.append((time.perf_counter()-start)*1000)
timings["adb_screenshot"] = {"median_ms": round(statistics.median(values), 2)}
report = {"captured_at": datetime.now().isoformat(timespec="seconds"), "live_before": live,
          "plays": len(plays), "confirmed": sum(p["confirmed"] for p in plays),
          "confirmation_rate": round(sum(p["confirmed"] for p in plays)/len(plays), 4),
          "intervals_seconds": {"median": statistics.median(intervals), "p10": float(np.percentile(intervals, 10)), "p90": float(np.percentile(intervals, 90))},
          "waits_at_8plus": sum(r.get("cues", {}).get("elixir", 0) is not None and r.get("cues", {}).get("elixir", 0) >= 8 for r in observed),
          "observations": len(observed), "wait_reasons": dict(Counter(r.get("observation", {}).get("reason") for r in observed)),
          "threat_kinds": dict(Counter(t.get("kind") for r in plays for t in r.get("cues", {}).get("threats", []))),
          "timings": timings, "failed_samples": failed[-12:]}
(ROOT / "outputs/RANDOM_FLUENCY_BASELINE.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
