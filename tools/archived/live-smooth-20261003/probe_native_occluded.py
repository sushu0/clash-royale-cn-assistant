"""Capture the renderer only, including current window occlusion evidence."""
import hashlib
import json
import statistics
import time

import numpy as np

from probe_native_capture import OUT, capture, collect, info, user32

tops = collect()
parents = [w for w in tops if w["title"] == "MEmu" and w["visible"]
           and min(w["client_size"]) > 200]
parent = parents[0]
render = [w for w in collect(parent["hwnd"]) if w["title"] == "RenderWindowWindow"][0]
report = {"foreground": info(user32.GetForegroundWindow()), "parent": parent,
          "renderer": render, "visible_z_order_before_parent": [], "frames": []}
for w in tops:
    if w["hwnd"] == parent["hwnd"]:
        break
    if w["visible"] and min(w["client_size"]) > 200:
        report["visible_z_order_before_parent"].append(w)
previous = None
started = time.monotonic()
for index in range(20):
    image, metrics = capture(render["hwnd"])
    pixels = np.asarray(image)
    metrics.update({"mean": float(pixels.mean()), "std": float(pixels.std()),
                    "hash": hashlib.sha256(image.tobytes()).hexdigest(),
                    "diff": None if previous is None else
                    float(np.abs(pixels.astype(float) - previous).mean())})
    previous = pixels.astype(float)
    if index in (0, 19):
        name = f"occluded-render-{index:02d}.png"
        image.save(OUT / name)
        metrics["image"] = name
    report["frames"].append(metrics)
    time.sleep(0.05)
report["elapsed"] = time.monotonic() - started
report["median_ms"] = statistics.median(f["total_ms"] for f in report["frames"])
report["unique"] = len({f["hash"] for f in report["frames"]})
(OUT / "native-occluded-probe.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps({k: v for k, v in report.items() if k != "frames"}, indent=2))
