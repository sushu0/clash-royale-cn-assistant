"""Summarize fixed Tencent 1v1 pilots from frozen traces and result PNGs."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parent
PILOTS = tuple(ROOT / f"pilot-{number:02d}" for number in range(2, 10))


def _gold_crowns(frame: np.ndarray) -> tuple[int, int, int, int]:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    gold = ((hsv[:, :, 0] >= 10) & (hsv[:, :, 0] <= 45)
            & (hsv[:, :, 1] >= 100) & (hsv[:, :, 2] >= 140))
    opponent_pixels = int(np.count_nonzero(gold[85:145, 80:340]))
    own_pixels = int(np.count_nonzero(gold[280:345, 80:340]))

    def crowns(pixels: int) -> int:
        return 3 if pixels >= 6000 else 2 if pixels >= 3900 else 1 if pixels >= 1700 else 0

    return crowns(opponent_pixels), crowns(own_pixels), opponent_pixels, own_pixels


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> dict:
    games = []
    for pilot in PILOTS:
        status = json.loads((pilot / "capture-status.json").read_text(encoding="utf-8"))
        if status["status"] != "complete" or not status["verified_final_lobby"]:
            raise RuntimeError(f"Pilot did not finish at lobby: {pilot}")
        if status["missing_evidence_count"]:
            raise RuntimeError(f"Missing frozen evidence: {pilot}")
        events = _read_jsonl(pilot / "events.jsonl")
        starts = {e["battle"]: e for e in events if e["event"] == "battle_start" and not e.get("resumed")}
        ends = [e for e in events if e["event"] == "battle_end"]
        if len(ends) != status["last_battle"] - status["first_battle"] + 1:
            raise RuntimeError(f"Incomplete result count: {pilot}")
        for end in ends:
            number = end["battle"]
            if number not in starts:
                raise RuntimeError(f"Missing battle start: {pilot} #{number}")
            sha = end["evidence"]["sha256"]
            image = pilot / "evidence" / f"{sha}.png"
            if not image.is_file() or hashlib.sha256(image.read_bytes()).hexdigest() != sha:
                raise RuntimeError(f"Result image hash failed: {pilot} #{number}")
            frame = cv2.imread(str(image))
            if frame is None or frame.shape != (633, 419, 3):
                raise RuntimeError(f"Invalid result image: {image}")
            opponent_crowns, own_crowns, top_gold, bottom_gold = _gold_crowns(frame)
            review = pilot / f"result-review-battle-{number:02d}.json"
            reviewed = json.loads(review.read_text(encoding="utf-8"))["reviewed_result"] if review.is_file() else None
            result = reviewed or end["result"]
            if result not in ("胜利", "失败"):
                raise RuntimeError(f"Unreviewed unknown outcome: {pilot} #{number}")
            plays = [e for e in events if e["event"] == "play" and e.get("battle") == number]
            categories = Counter(e["decision"]["category"] for e in plays)
            cards = Counter(e["decision"]["card"] for e in plays)
            start_time = datetime.fromisoformat(starts[number]["time"])
            end_time = datetime.fromisoformat(end["time"])
            duration = round((end_time - start_time).total_seconds())
            games.append({
                "pilot": pilot.name, "battle": number, "result": result,
                "raw_result": end["result"], "duration_seconds": duration,
                "opponent_crowns": opponent_crowns, "own_crowns": own_crowns,
                "opponent_crown_gold_pixels": top_gold, "own_crown_gold_pixels": bottom_gold,
                "confirmed_deployments": end["confirmed"], "attempts": end["attempts"],
                "categories": dict(categories), "cards": dict(cards),
                "result_sha256": sha,
            })
    summary = {
        "pilot_games": len(games),
        "wins": sum(g["result"] == "胜利" for g in games),
        "losses": sum(g["result"] == "失败" for g in games),
        "raw_unknown_reviewed": sum(g["raw_result"] == "未知" for g in games),
        "three_crown_losses": sum(g["result"] == "失败" and g["opponent_crowns"] == 3 for g in games),
        "losses_under_120_seconds": sum(g["result"] == "失败" and g["duration_seconds"] < 120 for g in games),
        "wins_without_defense_actions": sum(g["result"] == "胜利" and not g["categories"].get("defense", 0) for g in games),
        "battle_flow_lobby_verified_for_every_pilot": True,
        "result_image_sha256_verified_for_every_game": True,
    }
    return {"summary": summary, "games": games}


if __name__ == "__main__":
    report = main()
    output = ROOT / "audit-pilots-02-through-09.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(output)
