"""Read-only 25 FPS renderer benchmark, for a bounded 2.4 seconds."""
import hashlib
import json
import statistics
import time

from probe_native_capture import OUT, capture, collect, info, user32

parent = next(w for w in collect() if w["title"] == "MEmu"
              and w["visible"] and min(w["client_size"]) > 200)
render = next(w for w in collect(parent["hwnd"])
              if w["title"] == "RenderWindowWindow")
durations = []
hashes = []
times = []
begin = time.perf_counter()
for index in range(60):
    start = time.perf_counter()
    image, metadata = capture(render["hwnd"])
    image = image.resize((419, 633))
    durations.append((time.perf_counter() - start) * 1000)
    times.append(time.perf_counter())
    hashes.append(hashlib.sha256(image.tobytes()).hexdigest())
    time.sleep(max(0, begin + (index + 1) / 25 - time.perf_counter()))
result = {"renderer": render, "foreground": info(user32.GetForegroundWindow()),
          "elapsed_seconds": time.perf_counter() - begin,
          "actual_frame_delivery_fps": (len(times) - 1) / (times[-1] - times[0]),
          "frame_count": len(times), "unique_frames": len(set(hashes)),
          "median_capture_resize_ms": statistics.median(durations),
          "p95_capture_resize_ms": sorted(durations)[56],
          "max_capture_resize_ms": max(durations),
          "durations_ms": durations}
(OUT / "native-25fps-probe.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps({k: v for k, v in result.items() if k != "durations_ms"}, indent=2))
