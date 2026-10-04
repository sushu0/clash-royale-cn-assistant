"""Create scoped hand references and held-out crops from fixed real screenshots."""
import hashlib
import json
from pathlib import Path

import cv2

ROOT = Path(r"D:\codex\CodexWork\clash")
SOURCE = ROOT / "work/no-play-20261003/vision-audit"
ASSETS = ROOT / "py-clash-bot/pyclashbot/detection/reference_images/cn_random_cards/hand_calibration_20261003"
FIXTURES = ROOT / "py-clash-bot/tests/fixtures/cn_random_hand/calibration_20261003"
ASSETS.mkdir(parents=True, exist_ok=True)
FIXTURES.mkdir(parents=True, exist_ok=True)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


samples = []
for number in (37, 40):
    path = SOURCE / f"recent-battle-{number:02d}.png"
    frame = cv2.imread(str(path))
    for variant, slot, cost in (("evo_witch", 1, 5), ("bandit", 2, 3), ("goblin_hut", 3, 4)):
        left = (115, 182, 249, 316)[slot]
        roi = [left, 529, left + 54, 595]
        name = f"{variant}-{number}.png"
        cv2.imwrite(str(ASSETS / name), frame[529:595, left:left + 54])
        samples.append({"file": name, "sha256": sha(ASSETS / name), "variant": variant,
                        "observed_cost": cost, "source_path": str(path), "source_sha256": sha(path),
                        "source_session": "20261003-182719", "source_roi": roi,
                        "cost_source_roi": [(133, 199, 266, 334)[slot], (582, 583, 583, 582)[slot],
                                            (153, 219, 286, 354)[slot], (602, 603, 603, 602)[slot]]})

manifest = {"schema_version": 1, "resolution": [419, 633], "channel_order": "BGR",
            "purpose": "Supplement missing/current Chinese hand artwork without relaxing old fingerprint gates",
            "observed_cost_note": "Current goblin_hut cost 4 is observed on source frames; global catalog remains unchanged",
            "samples": samples}
(ASSETS / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

held_out = []
for name in ("recent-battle-38.png", "recent-battle-41.png", "recent-battle-43.png", "recent-battle-44.png", "user-game-crop.png"):
    source = SOURCE / name
    frame = cv2.imread(str(source))
    # Tests restore the crop at its real coordinates; all recognition inputs are retained.
    cv2.imwrite(str(FIXTURES / name), frame[510:620, 105:388])
    held_out.append({"file": name, "sha256": sha(FIXTURES / name), "source_path": str(source),
                     "source_sha256": sha(source), "source_roi": [105, 510, 388, 620],
                     "expected_cards": ["earthquake", "witch", "bandit", "goblin_hut"],
                     "expected_variants": ["earthquake", "evo_witch", "bandit", "goblin_hut"],
                     "expected_costs": [3, 5, 3, 4]})
(FIXTURES / "manifest.json").write_text(json.dumps(held_out, indent=2), encoding="utf-8")
print(json.dumps({"runtime_assets": str(ASSETS), "samples": len(samples), "held_out": len(held_out)}))
