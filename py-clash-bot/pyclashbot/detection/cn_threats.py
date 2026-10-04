"""Small, conservative visual threat hints from real Tencent sprite crops.

The caller must confirm a battle screen. Supplied enemy-label anchors are
searched by default; an opt-in narrow early-balloon pass also verifies a red
numeral. No match means unknown, not safe. No model or device/network I/O.
"""

import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from pyclashbot.bot.coords import CN_HOG_DEFENSE_ROI, CN_HOG_EARLY_AIR_ROI
from pyclashbot.utils.runtime_config import resource_path

_FOLDER = resource_path("pyclashbot/detection/reference_images/cn_threats")
_567_FOLDER = _FOLDER.parent / "cn_567_threats"
_DEFAULT_THRESHOLD = 0.88
_SEARCH_JITTER = 8


class ThreatTemplateError(RuntimeError):
    """A broken bank is an environment fault, never an empty enemy observation."""


def approved_threat(signal: dict) -> bool:
    """Honor the detector's calibrated threshold instead of imposing another .88."""
    if not isinstance(signal, dict) or signal.get("approved") is False:
        return False
    confidence = signal.get("confidence")
    threshold = signal.get("confidence_threshold", _DEFAULT_THRESHOLD)
    if (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not isinstance(threshold, (int, float))
        or isinstance(threshold, bool)
    ):
        return False
    if not math.isfinite(confidence) or not math.isfinite(threshold):
        return False
    return 0 <= threshold <= 1 and threshold <= confidence <= 1


def _sha_valid(value) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _manifest_items(folder: Path) -> tuple[list[dict], str]:
    try:
        raw = (folder / "manifest.json").read_bytes()
        items = json.loads(raw)
    except (OSError, ValueError) as error:
        raise ThreatTemplateError(f"Threat manifest cannot be read: {folder}: {error}") from error
    if not isinstance(items, list) or not items:
        raise ThreatTemplateError(f"Threat manifest must be a non-empty list: {folder}")
    files = set()
    for item in items:
        if not isinstance(item, dict):
            raise ThreatTemplateError(f"Threat manifest entry must be an object: {folder}")
        filename = item.get("file")
        threshold = item.get("threshold")
        anchor = item.get("anchor_offset")
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or not filename.lower().endswith(".png")
            or filename in files
            or not isinstance(item.get("id"), str)
            or not item["id"]
            or type(item.get("enabled")) is not bool
            or item.get("kind") not in {"ground", "air", "rush", "swarm"}
            or type(threshold) not in (int, float)
            or not math.isfinite(threshold)
            or not 0 < threshold <= 1
            or not isinstance(anchor, list)
            or len(anchor) != 2
            or any(type(value) is not int for value in anchor)
            or not _sha_valid(item.get("template_sha256"))
            or not _sha_valid(item.get("source_sha256"))
            or not isinstance(item.get("source"), str)
        ):
            raise ThreatTemplateError(f"Invalid threat manifest schema: {folder}/{filename}")
        files.add(filename)
        red_fraction = item.get("min_red_fraction", 0)
        if type(red_fraction) not in (int, float) or not math.isfinite(red_fraction) or not 0 <= red_fraction <= 1:
            raise ThreatTemplateError(f"Invalid color threshold: {folder}/{filename}")
        if folder.name == "cn_567_threats":
            band = item.get("tag_search_bbox")
            if (
                not isinstance(band, list)
                or len(band) != 4
                or any(type(value) is not int for value in band)
                or band[2] <= band[0]
                or band[3] <= band[1]
                or not isinstance(item.get("independent_validation_sources"), list)
                or not item["independent_validation_sources"]
            ):
                raise ThreatTemplateError(f"Missing independent role calibration: {folder}/{filename}")
    return items, hashlib.sha256(raw).hexdigest()


def _bank_signature(folder: Path) -> tuple:
    items, manifest_hash = _manifest_items(folder)
    signatures = []
    for item in items:
        if not item["enabled"]:
            continue
        try:
            stat = (folder / item["file"]).stat()
        except OSError as error:
            raise ThreatTemplateError(f"Missing threat template: {folder}/{item['file']}") from error
        signatures.append((item["file"], stat.st_mtime_ns, stat.st_size))
    if not signatures:
        raise ThreatTemplateError(f"No enabled threat templates: {folder}")
    return manifest_hash, tuple(signatures)


@lru_cache(maxsize=8)
def _load_bank(folder_name: str, signature: tuple) -> tuple[dict, ...]:
    folder = Path(folder_name)
    items, manifest_hash = _manifest_items(folder)
    if manifest_hash != signature[0]:
        raise ThreatTemplateError(f"Threat manifest changed during loading: {folder}")
    loaded = []
    for item in items:
        if not item["enabled"]:
            continue
        path = folder / item["file"]
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise ThreatTemplateError(f"Threat template cannot be read: {path}") from error
        if hashlib.sha256(raw).hexdigest() != item["template_sha256"]:
            raise ThreatTemplateError(f"Threat template hash mismatch: {path}")
        color = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if color is None or color.size == 0 or np.all(color == 0) or np.all(color == 255):
            raise ThreatTemplateError(f"Invalid threat image: {path}")
        gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
        color.flags.writeable = gray.flags.writeable = False
        loaded.append({**item, "color": color, "gray": gray})
    return tuple(loaded)


def _templates() -> tuple[dict, ...]:
    return _load_bank(str(_FOLDER), _bank_signature(_FOLDER))


def _567_templates() -> tuple[dict, ...]:
    """Opt-in role crops with separately validated asset integrity."""
    return _load_bank(str(_567_FOLDER), _bank_signature(_567_FOLDER))


def threat_template_health(*, include_567=False, force=False) -> dict:
    """Expose bank faults before a runner starts; force rehashes cached images."""
    if force:
        _load_bank.cache_clear()
        _load_label_bank.cache_clear()
    banks, errors = {}, []
    for folder in (_FOLDER, _567_FOLDER) if include_567 else (_FOLDER,):
        try:
            templates = _load_bank(str(folder), _bank_signature(folder))
            banks[folder.name] = {
                "templates": len(templates),
                "manifest_sha256": _bank_signature(folder)[0],
                "template_sha256": {item["file"]: item["template_sha256"] for item in templates},
            }
        except ThreatTemplateError as error:
            errors.append(str(error))
    try:
        labels = _567_label_templates() if include_567 else _early_label_templates()
        banks["cn_enemy_tags"] = {"templates": len(labels)}
    except ThreatTemplateError as error:
        errors.append(str(error))
    return {"status": "invalid" if errors else "healthy", "banks": banks, "errors": errors}


def _label_bank(recursive: bool) -> tuple[np.ndarray, ...]:
    folder = resource_path("pyclashbot/detection/reference_images/cn_enemy_tags")
    try:
        raw = (folder / "integrity.json").read_bytes()
        data = json.loads(raw)
        if (
            not isinstance(data, dict)
            or data.get("schema") != "cn-enemy-tags/integrity-v1"
            or not isinstance(data.get("files"), dict)
            or not data["files"]
        ):
            raise ValueError("invalid label integrity schema")
        paths = sorted(folder.rglob("*.png") if recursive else folder.glob("*.png"))
        if not paths:
            raise ValueError("no hostile level templates")
        signatures = []
        for path in paths:
            relative = path.relative_to(folder).as_posix()
            expected = data["files"].get(relative)
            if not _sha_valid(expected):
                raise ValueError(f"label has no hash: {relative}")
            stat = path.stat()
            signatures.append((relative, stat.st_mtime_ns, stat.st_size, expected))
        required = {name for name in data["files"] if recursive or "/" not in name}
        if required != {item[0] for item in signatures}:
            raise ValueError("hostile label bank has missing or unregistered images")
    except (OSError, ValueError) as error:
        raise ThreatTemplateError(f"Invalid hostile-label bank: {folder}: {error}") from error
    return _load_label_bank(str(folder), hashlib.sha256(raw).hexdigest(), tuple(signatures))


@lru_cache(maxsize=8)
def _load_label_bank(folder: str, manifest_hash: str, signatures: tuple) -> tuple[np.ndarray, ...]:
    images = []
    for name, _mtime, _size, expected in signatures:
        path = Path(folder) / name
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise ThreatTemplateError(f"Missing hostile-label image: {path}") from error
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ThreatTemplateError(f"Hostile-label hash mismatch: {path}")
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
        if image is None or image.size == 0:
            raise ThreatTemplateError(f"Invalid hostile-label image: {path}")
        image.flags.writeable = False
        images.append(image)
    return tuple(images)


def _567_label_templates() -> tuple[np.ndarray, ...]:
    return _label_bank(True)


def _567_roles(frame: np.ndarray, hsv: np.ndarray) -> list[dict]:
    """Recover only two calibrated roles AND an adjacent hostile level plaque.

    Ordinary label detection misses some 11-level plaques. A matched sprite
    alone never supplies an enemy: a red plaque and white/gold numeral are
    required in the role's narrow relative label band. Unknown poses abstain.
    """
    x1 = min(CN_HOG_EARLY_AIR_ROI[0], CN_HOG_DEFENSE_ROI[0])
    y1 = min(CN_HOG_EARLY_AIR_ROI[1], CN_HOG_DEFENSE_ROI[1])
    x2 = max(CN_HOG_EARLY_AIR_ROI[2], CN_HOG_DEFENSE_ROI[2])
    y2 = max(CN_HOG_EARLY_AIR_ROI[3], CN_HOG_DEFENSE_ROI[3])
    region = frame[y1:y2, x1:x2]
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    found = []
    for template in _567_templates():
        height, width = template["color"].shape[:2]
        scores = np.minimum(
            cv2.matchTemplate(region, template["color"], cv2.TM_CCOEFF_NORMED),
            cv2.matchTemplate(gray, template["gray"], cv2.TM_CCOEFF_NORMED),
        )
        threshold = float(template["threshold"])
        for _ in range(4):
            _, confidence, _, (rx, ry) = cv2.minMaxLoc(scores)
            if not np.isfinite(confidence) or confidence < threshold:
                break
            scores[max(0, ry - height // 2) : ry + height // 2 + 1, max(0, rx - width // 2) : rx + width // 2 + 1] = -1
            sx, sy = rx + x1, ry + y1
            dx1, dy1, dx2, dy2 = template["tag_search_bbox"]
            lx1, ly1 = max(0, sx + dx1), max(0, sy + dy1)
            lx2, ly2 = min(419, sx + dx2), min(633, sy + dy2)
            band = cv2.cvtColor(frame[ly1:ly2, lx1:lx2], cv2.COLOR_BGR2GRAY)
            best = None
            for glyph in _567_label_templates():
                gh, gw = glyph.shape
                if band.shape[0] < gh or band.shape[1] < gw:
                    continue
                _, label_score, _, (tx, ty) = cv2.minMaxLoc(cv2.matchTemplate(band, glyph, cv2.TM_CCOEFF_NORMED))
                if label_score < 0.75:
                    continue
                xx, yy = lx1 + tx, ly1 + ty
                tag = hsv[yy : yy + gh, xx : xx + gw]
                red = ((tag[:, :, 0] <= 9) | (tag[:, :, 0] >= 166)) & (tag[:, :, 1] >= 125) & (tag[:, :, 2] >= 75)
                numeral = ((tag[:, :, 1] <= 90) & (tag[:, :, 2] >= 190)) | (
                    (tag[:, :, 0] >= 16) & (tag[:, :, 0] <= 38) & (tag[:, :, 1] >= 90) & (tag[:, :, 2] >= 180)
                )
                blue = (tag[:, :, 0] >= 85) & (tag[:, :, 0] <= 135) & (tag[:, :, 1] >= 100) & (tag[:, :, 2] >= 80)
                if np.count_nonzero(red) < 18 or np.count_nonzero(numeral) < 7 or np.count_nonzero(blue) > 6:
                    continue
                if best is None or label_score > best[0]:
                    best = (label_score, xx + gw // 2, yy + gh // 2 + 16)
            if best is None:
                continue
            label_score, ex, ey = best
            found.append(
                {
                    "kind": template["kind"],
                    "x": ex,
                    "y": ey,
                    "confidence": round(float(confidence), 5),
                    "confidence_threshold": threshold,
                    "template_id": template["id"],
                    "sprite_bbox": [sx, sy, width, height],
                    "source": template["source"],
                    "source_sha256": template["source_sha256"],
                    "origin": "567_role",
                    "label_confidence": round(float(label_score), 5),
                    **{key: template[key] for key in ("heavy", "role", "small", "domain") if key in template},
                }
            )
    return [{**item, "approved": True} for item in found]


def _early_label_templates() -> tuple[np.ndarray, ...]:
    return _label_bank(False)


def _early_air(frame: np.ndarray, hsv: np.ndarray, templates: tuple[dict, ...]) -> list[dict]:
    """Admit only a proven balloon envelope AND its red numeral above it."""
    x1, y1, x2, y2 = CN_HOG_EARLY_AIR_ROI
    region = frame[y1:y2, x1:x2]
    region_gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    found = []
    for template in templates:
        if template["id"] != "air_balloon_envelope" or template["kind"] != "air":
            continue
        height, width = template["color"].shape[:2]
        color_scores = cv2.matchTemplate(region, template["color"], cv2.TM_CCOEFF_NORMED)
        gray_scores = cv2.matchTemplate(region_gray, template["gray"], cv2.TM_CCOEFF_NORMED)
        scores = np.minimum(color_scores, gray_scores)
        threshold = float(template["threshold"])
        for _ in range(3):
            _, confidence, _, (rx, ry) = cv2.minMaxLoc(scores)
            if not np.isfinite(confidence) or confidence < threshold:
                break
            scores[max(0, ry - height // 2) : ry + height // 2 + 1, max(0, rx - width // 2) : rx + width // 2 + 1] = -1
            sx, sy = rx + x1, ry + y1
            body = hsv[sy : sy + height, sx : sx + width]
            red_fraction = float(
                np.mean(
                    ((body[:, :, 0] <= 12) | (body[:, :, 0] >= 166)) & (body[:, :, 1] >= 110) & (body[:, :, 2] >= 130)
                )
            )
            if red_fraction < float(template.get("min_red_fraction", 0.60)):
                continue
            # Search the tiny label band immediately above the matched hull.
            # This works even when red balloon pixels connect to its plaque.
            lx1, ly1 = max(0, sx - 4), max(0, sy - 14)
            lx2, ly2 = min(419, sx + width + 4), min(633, sy + 4)
            band = cv2.cvtColor(frame[ly1:ly2, lx1:lx2], cv2.COLOR_BGR2GRAY)
            best_tag = None
            for glyph in _early_label_templates():
                gh, gw = glyph.shape
                if band.shape[0] < gh or band.shape[1] < gw:
                    continue
                _, tag_score, _, (tx, ty) = cv2.minMaxLoc(cv2.matchTemplate(band, glyph, cv2.TM_CCOEFF_NORMED))
                if tag_score < 0.75:
                    continue
                x, y = lx1 + tx, ly1 + ty
                tag = hsv[y : y + gh, x : x + gw]
                red = ((tag[:, :, 0] <= 9) | (tag[:, :, 0] >= 166)) & (tag[:, :, 1] >= 125) & (tag[:, :, 2] >= 75)
                white = (tag[:, :, 1] <= 90) & (tag[:, :, 2] >= 190)
                if np.count_nonzero(red) < 18 or np.count_nonzero(white) < 10:
                    continue
                if best_tag is None or tag_score > best_tag[0]:
                    best_tag = (tag_score, x + gw // 2, y + gh // 2)
            if best_tag is None:
                continue
            tag_score, ex, tag_y = best_tag
            ey = tag_y + 16  # never clamp this anchor to the old ROI boundary
            if any(abs(ex - r["x"]) <= 12 and abs(ey - r["y"]) <= 12 for r in found):
                continue
            found.append(
                {
                    "kind": "air",
                    "x": ex,
                    "y": ey,
                    "confidence": round(float(confidence), 5),
                    "confidence_threshold": threshold,
                    "red_fraction": round(red_fraction, 5),
                    "template_id": template["id"],
                    "sprite_bbox": [sx, sy, width, height],
                    "source": template["source"],
                    "source_sha256": template["source_sha256"],
                    "origin": "early_air",
                    "label_confidence": round(float(tag_score), 5),
                }
            )
    return found


def read_cn_threats(frame: np.ndarray, enemies=None, *, include_early_air=False, include_567=False) -> list[dict]:
    """Return high-confidence air/rush/swarm hints at existing enemy markers.

    x/y preserve the input marker (label center +16), not a measured footpoint.
    confidence is the minimum of color and grayscale normalized correlation,
    not a calibrated probability. Sprite crops exclude level digits. Unknown
    or unrepresented units are omitted. A high score is useful only near the
    associated currently visible enemy label, never for an entire lane.
    ``include_567`` additionally admits the separately calibrated role bank;
    its limited sprite scan still requires a matching hostile level plaque.
    Its ground result carries ``heavy``; absent roles remain unknown.
    """
    if not isinstance(frame, np.ndarray) or frame.shape != (633, 419, 3) or frame.dtype != np.uint8:
        return []
    templates = _templates() + (_567_templates() if include_567 else ())
    if not templates or (not enemies and not include_early_air and not include_567):
        return []
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    found = []
    for enemy in enemies or ():
        if len(enemy) != 2:
            continue
        ex, ey = int(enemy[0]), int(enemy[1])
        if not (10 <= ex < 409 and 25 <= ey < 480):
            continue
        tag = hsv[ey - 23 : ey - 8, ex - 7 : ex + 8]
        red = ((tag[:, :, 0] <= 9) | (tag[:, :, 0] >= 166)) & (tag[:, :, 1] >= 125) & (tag[:, :, 2] >= 75)
        if np.count_nonzero(red) < 20:
            continue
        candidates: list[dict] = []
        for template in templates:
            if template.get("early_only", False) or template.get("role_recovery_only", False):
                continue
            dx, dy = template["anchor_offset"]
            height, width = template["color"].shape[:2]
            x1, y1 = max(0, ex + dx - _SEARCH_JITTER), max(0, ey + dy - _SEARCH_JITTER)
            x2 = min(419, ex + dx + width + _SEARCH_JITTER)
            y2 = min(510, ey + dy + height + _SEARCH_JITTER)
            roi = frame[y1:y2, x1:x2]
            if roi.shape[0] < height or roi.shape[1] < width:
                continue
            color_scores = cv2.matchTemplate(roi, template["color"], cv2.TM_CCOEFF_NORMED)
            gray_scores = cv2.matchTemplate(
                cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY), template["gray"], cv2.TM_CCOEFF_NORMED
            )
            scores = np.minimum(color_scores, gray_scores)
            _, confidence, _, (x, y) = cv2.minMaxLoc(scores)
            threshold = float(template.get("threshold", _DEFAULT_THRESHOLD))
            if not np.isfinite(confidence) or confidence < threshold:
                continue
            matched_hsv = hsv[y1 + y : y1 + y + height, x1 + x : x1 + x + width]
            red_body = (
                ((matched_hsv[:, :, 0] <= 12) | (matched_hsv[:, :, 0] >= 166))
                & (matched_hsv[:, :, 1] >= 110)
                & (matched_hsv[:, :, 2] >= 130)
            )
            red_fraction = float(np.mean(red_body))
            if red_fraction < float(template.get("min_red_fraction", 0)):
                continue
            candidates.append(
                {
                    "kind": template["kind"],
                    "x": ex,
                    "y": ey,
                    "confidence": round(float(confidence), 5),
                    "confidence_threshold": threshold,
                    "red_fraction": round(red_fraction, 5),
                    "template_id": template["id"],
                    "sprite_bbox": [x1 + x, y1 + y, width, height],
                    "source": template["source"],
                    "source_sha256": template["source_sha256"],
                    **{key: template[key] for key in ("heavy", "role", "small", "domain") if key in template},
                }
            )
        if candidates:
            candidates.sort(key=lambda candidate: candidate["confidence"], reverse=True)
            top = candidates[0]
            rivals = [
                candidate
                for candidate in candidates[1:]
                if (candidate["kind"], candidate.get("heavy")) != (top["kind"], top.get("heavy"))
            ]
            if not rivals or top["confidence"] - rivals[0]["confidence"] >= 0.05:
                if not any(item["kind"] == top["kind"] and item["sprite_bbox"] == top["sprite_bbox"] for item in found):
                    found.append(top)
    if include_early_air:
        for candidate in _early_air(frame, hsv, templates):
            if not any(
                r["template_id"] == candidate["template_id"]
                and abs(r["x"] - candidate["x"]) <= 12
                and abs(r["y"] - candidate["y"]) <= 12
                for r in found
            ):
                found.append(candidate)
    if include_567:
        for candidate in _567_roles(frame, hsv):
            if not any(
                item["template_id"] == candidate["template_id"]
                and abs(item["x"] - candidate["x"]) <= 7
                and abs(item["y"] - candidate["y"]) <= 7
                for item in found
            ):
                found.append(candidate)
    return [{**item, "approved": True} for item in found]
