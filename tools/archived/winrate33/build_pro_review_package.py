"""Build a bounded, source-backed review bundle from frozen CN battle evidence."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path


TASK = Path(r"D:\codex\CodexWork\clash")
REPO = TASK / "py-clash-bot"
FROZEN = TASK / "work" / "winrate33"
OUTPUT = TASK / "outputs" / "PRO_STRATEGY_REVIEW_20260927.zip"

SOURCES = [
    "pyclashbot/bot/hog_cycle_strategy.py",
    "pyclashbot/bot/cn_1v1_loop.py",
    "pyclashbot/bot/elite_ice_golem_ability.py",
    "pyclashbot/bot/coords.py",
    "pyclashbot/bot/card_detection.py",
    "pyclashbot/detection/cn_battle_cues.py",
    "pyclashbot/detection/cn_threats.py",
    "tests/test_cn_hog_strategy.py",
    "tests/test_cn_battle_cues.py",
    "tests/test_cn_threats.py",
    "tests/test_cn_loop_observation.py",
    "tests/test_cn_elite_ability.py",
    "pyproject.toml",
]

CASES = [
    ("01-static-xbow-right", "pilot-13", 2, "09:45:45", "09:46:05", None),
    ("02-mixed-right-push", "pilot-12", 9, "08:47:15", "08:47:33", None),
    ("03-split-push-last-four", "pilot-09", 1, "06:16:02", "06:16:10", None),
    ("04-six-hogs-zero-spells", "pilot-10", 2, None, None, "hog"),
    ("05-right-collapse-split", "pilot-14", 8, "10:51:05", "10:51:30", None),
]

README = """# 腾讯国服 2.6 速猪机器人：Pro 源码与真实帧复核包

此包供审查，不代表新策略已部署或达到 33/100。运行版本是 V5n；机器人停在大厅。
`source/` 是打包时的源码与测试副本。`cases/` 是永久冻结的实战截图和
精简事件；`manifest.json` 给出每个条目的 SHA-256。截图保留原像素、未重绘。

## 对原诊断的重要补充

在 `early-half-tower-losses-02-through-14.json` 的 63 个可读半血败局中，
开局 45 秒内右塔先半血有 30 局。对这 30 局的日志做只读检查：30 局在半血前
的记录帧中均出现过右路 `far_warnings`，27 局出现过右路近场标记，23 局在
半血前 15 秒内已经确认向右路下过 `category=defense` 的牌。
日志的 `observe` 约十秒才持久保存一次，`play` 保存动作前后帧；这些数值
不能当作连续视频的真实漏检率。它们说明“右路完全未被看到/未进入预算”
并不足以解释多数早崩，必须进一步区分防守牌是否真能命中、牵引或输出。

- 案例 01：右侧敌半场静止 X-Bow 已锁住我方右塔；`far_warnings` 约在
  `(306,205)`，而机器人仍向左出猪，右塔从 4270 降至 2345。现有移动深色
  提示不会覆盖该源。不能从一次战例直接上线通用建筑识别。
- 案例 02：右路地面与空中混合推进。机器人先下冰人、冰精灵，后来下炮，
  右塔仍快速失血。不能把所有右路早期预警都当成炮可解决的地面目标。
- 案例 03：右路已下火枪，左路也有三名标记；机器人把剩余四费火球投向
  右侧，左侧随后缺少及时防守。源码后来加了特例，但尚未证明覆盖所有分推。
- 案例 04：同一局确认六次野猪，敌左塔可读血条在中后段基本停滞，整局
  没有 `category=spell` 动作。血条变化还可能由其他我方单位造成。
- 案例 05：双路均有压力，右塔很快降至 1044；普通左路炮和后来的右路
  火球并未及时止损。

请先审查原始截图与源码，再决定是否实施时间预算/双路可行性。尤其要检查：
1. 右塔早崩的 23 个已防守样本中，牌型/落点/生效时间具体错在哪里；
2. 右塔在无近场红标记时受静止远程源攻击的发生频次及可用响应；
3. `far_warnings` 的同帧重复与跨帧关联，不能把标记数等同真实兵数；
4. 现有出牌确认期间确实会读取 `after_frame`，但并未把这些帧交给策略
   更新两路观察；新增观测不得并发点击或复用同一帧冒充独立帧。

目前未修改、未重测或重新部署策略。本包只提供诊断材料。
"""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    manifest: dict[str, str] = {}
    case_counts: dict[str, dict[str, int]] = {}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6) as archive:
        def add(name: str, data: bytes) -> None:
            archive.writestr(name, data)
            manifest[name] = digest(data)

        add("README.md", README.encode("utf-8"))
        add("reference/WINRATE33_PROGRESS.md",
            (TASK / "outputs" / "WINRATE33_PROGRESS.md").read_bytes())
        add("reference/early-half-tower-losses-02-through-14.json",
            (FROZEN / "early-half-tower-losses-02-through-14.json").read_bytes())
        for relative in SOURCES:
            add("source/" + relative, (REPO / relative).read_bytes())
        for folder in ("cn_threats", "cn_enemy_tags", "cn_minimal"):
            for path in sorted((REPO / "pyclashbot" / "detection" /
                                "reference_images" / folder).rglob("*")):
                if path.is_file():
                    add("source/" + path.relative_to(REPO).as_posix(), path.read_bytes())

        for label, pilot, battle, start, end, selected_card in CASES:
            log = FROZEN / pilot / "events.jsonl"
            events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()
                      if line]
            if selected_card is not None:
                actions = [
                    {"time": event.get("time"), "decision": event.get("decision"),
                     "confirmed": event.get("confirmed"),
                     "enemy_tower_fill": event.get("cues", {}).get("enemy_tower_fill")}
                    for event in events
                    if event.get("battle") == battle and event.get("event") == "play"
                ]
                add(f"cases/{label}/all-play-decisions.json",
                    json.dumps(actions, ensure_ascii=False, indent=2).encode("utf-8"))
            selected = []
            image_names: set[str] = set()
            for event in events:
                if event.get("battle") != battle:
                    continue
                if event.get("event") not in ("play", "observe", "battle_end"):
                    continue
                if start is not None and not start <= event.get("time", "")[-8:] <= end:
                    continue
                if selected_card is not None and event.get("event") == "play":
                    if event.get("decision", {}).get("card") != selected_card:
                        continue
                elif selected_card is not None and event.get("event") == "observe":
                    continue
                compact = {key: event[key] for key in ("event", "battle", "time", "decision",
                          "hand", "cues", "confirmed", "timing_ms", "policy_version")
                           if key in event}
                compact["screenshots"] = {}
                for kind, record in event.get("captured_evidence", {}).items():
                    path_string = record.get("frozen_path")
                    if not path_string:
                        continue
                    image_path = Path(path_string)
                    if not image_path.is_file():
                        raise FileNotFoundError(image_path)
                    image_bytes = image_path.read_bytes()
                    if digest(image_bytes) != record.get("expected_sha256"):
                        raise ValueError(f"Frozen screenshot hash mismatch: {image_path}")
                    image_name = f"cases/{label}/frames/{image_path.name}"
                    if image_name not in image_names:
                        add(image_name, image_bytes)
                        image_names.add(image_name)
                    compact["screenshots"][kind] = image_name
                selected.append(compact)
            if not selected:
                raise ValueError(f"No frozen events selected for {label}")
            add(f"cases/{label}/events.json",
                json.dumps(selected, ensure_ascii=False, indent=2).encode("utf-8"))
            case_counts[label] = {"events": len(selected), "screenshots": len(image_names)}
        add("manifest.json", json.dumps({"sha256": manifest, "cases": case_counts},
                                         ensure_ascii=False, indent=2).encode("utf-8"))
    print(json.dumps({"output": str(OUTPUT), "bytes": OUTPUT.stat().st_size,
                      "sha256": digest(OUTPUT.read_bytes()), "cases": case_counts},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
