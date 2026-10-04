"""Read-only retrospective audit; writes a JSON report without controlling the bot."""
import ast
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FMT = "%Y-%m-%d %H:%M:%S"
COST = {"hog": 4, "musketeer": 4, "cannon": 3, "fireball": 4, "ice_golem": 2, "log": 2, "ice_spirit": 1, "skeletons": 1}


def stamp(text):
    return datetime.strptime(text, FMT).timestamp()


def compact(row):
    return {key: row[key] for key in ("line", "time", "session", "battle", "event", "decision", "cues", "confirmed") if key in row}


def main():
    rows = []
    for line, text in enumerate((ROOT / "outputs/cn-hog-strategy.jsonl").read_text(encoding="utf-8").splitlines(), 1):
        row = json.loads(text)
        if row["time"] >= "2026-09-26":
            row.update(line=line, ts=stamp(row["time"]))
            rows.append(row)
    starts, sessions, recoveries, ends_log, resumed = {}, {}, [], {}, set()
    session = None
    was_resume = False
    for line, text in enumerate((ROOT / "outputs/cn-battles-live.log").read_text(encoding="utf-8").splitlines(), 1):
        if "连续对战已启动" in text:
            session = datetime.strptime(text[:19], FMT).strftime("%Y%m%d-%H%M%S")
            sessions[session] = {"started": text[:19], "log_line": line}
        if not session or not session.startswith("20260926"):
            continue
        if "策略源码校验: " in text:
            sessions[session]["runtime_hashes"] = ast.literal_eval(text.split("策略源码校验: ", 1)[1])
        if "恢复事件：接管" in text:
            was_resume = True
        match = re.search(r"对战开始 场次=(\d+)", text)
        if match:
            key = session, int(match[1])
            starts[key] = stamp(text[:19])
            if was_resume:
                resumed.add(key)
            was_resume = False
        match = re.search(r"对战结束 .*已完成=(\d+)", text)
        if match:
            ends_log[session, int(match[1])] = {"line": line, "text": text}
        if "恢复/重启" in text:
            recoveries.append({"session": session, "log_line": line, "text": text})
    by_session = defaultdict(list)
    for row in rows:
        by_session[row["session"]].append(row)
    report = {"created_at": datetime.now().strftime(FMT), "scope": "All 2026-09-26 trace sessions, completed battles only", "sessions": [], "recoveries": recoveries}
    for session, session_rows in sorted(by_session.items()):
        ends = [r for r in session_rows if r["event"] == "battle_end"]
        ids = {r["battle"] for r in ends}
        selected = [r for r in session_rows if r["battle"] in ids]
        plays = [r for r in selected if r["event"] == "play"]
        conf = [r for r in plays if r["confirmed"]]
        obs = [r for r in selected if r["event"] == "observe"]
        skills = [r for r in selected if r["event"] == "elite_ability"]
        duration = sum(r["ts"] - starts[session, r["battle"]] for r in ends)
        costs = Counter()
        for r in conf:
            costs[r["decision"]["category"]] += COST[r["decision"]["card"]]
        groups = defaultdict(list)
        for r in selected:
            groups[r["battle"]].append(r)
        gaps, combos, per_battle, late_confirm = [], [], [], []
        for end in ends:
            battle = end["battle"]
            group = groups[battle]
            cp = [r for r in group if r["event"] == "play" and r["confirmed"]]
            hogs = [r for r in cp if r["decision"]["card"] == "hog"]
            marks = [(starts[session, battle], "battle_start")] + [(r["ts"], r["time"]) for r in hogs] + [(end["ts"], "battle_end")]
            bc = sum(COST[r["decision"]["card"]] for r in cp)
            defensive = sum(COST[r["decision"]["card"]] for r in cp if r["decision"]["category"] in ("defense", "spell"))
            per_battle.append({"battle": battle, "result": end["result"], "seconds": end["ts"]-starts[session,battle], "hog_count": len(hogs), "nominal_cost": bc, "defense_spell_nominal_cost": defensive, "defense_spell_cost_share": defensive/bc if bc else None, "resumed": (session,battle) in resumed, "end_log": ends_log[session,battle]})
            for (begin, label1), (finish, label2) in zip(marks, marks[1:]):
                if finish - begin < 60:
                    continue
                inside = [r for r in group if begin < r["ts"] < finish]
                defensive_plays = [r for r in inside if r["event"] == "play" and r["confirmed"] and r["decision"]["category"] in ("defense", "spell")]
                affordable = [r for r in inside if r.get("cues", {}).get("elixir") is not None and r["cues"]["elixir"] >= 7 and any(h["card"] == "hog" and h["available"] for h in r.get("hand", []))]
                gaps.append({"battle": battle, "seconds": finish-begin, "from": datetime.fromtimestamp(begin).strftime(FMT), "to": datetime.fromtimestamp(finish).strftime(FMT), "boundary_types": [label1,label2], "defensive_confirmed": len(defensive_plays), "defensive_nominal_cost": sum(COST[r["decision"]["card"]] for r in defensive_plays), "affordable_hog_samples": len(affordable), "affordable_hog_examples": [compact(r) for r in affordable[:4]], "first_defensive_events": [compact(r) for r in defensive_plays[:5]]})
            for index, row in enumerate(group):
                if row["event"] != "play":
                    continue
                later = group[index+1:]
                if not row["confirmed"]:
                    slot = row["decision"]["slot"]
                    for nxt in later:
                        if nxt["ts"]-row["ts"] > 12 or nxt["event"] == "battle_end":
                            break
                        hand = nxt.get("hand", [])
                        card = next((h["card"] for h in hand if h["slot"] == slot), None)
                        if card and card != row["decision"]["card"]:
                            late_confirm.append({"attempt": compact(row), "next_slot_card": card, "observed_at": nxt["time"], "delay_seconds": nxt["ts"]-row["ts"]})
                            break
                        if nxt["event"] == "play" and nxt["decision"]["slot"] == slot:
                            break
                if row["confirmed"] and row["decision"]["card"] == "ice_golem" and row["decision"]["category"] == "attack":
                    next_hog = next((r for r in later if r["event"] == "play" and r["confirmed"] and r["decision"]["card"] == "hog"), None)
                    combos.append({"time": row["time"], "battle": battle, "line": row["line"], "hog_in_hand": any(h["card"] == "hog" for h in row["hand"]), "reason": row["decision"]["reason"], "next_hog_seconds": None if not next_hog else next_hog["ts"]-row["ts"], "pressure_samples_7s": sum(bool(r.get("cues",{}).get("enemies")) for r in later if r["ts"]-row["ts"]<=7)})
        full = [r for r in obs if r["cues"]["elixir"] == 10]
        cheap = [r for r in plays if r["decision"]["category"] == "defense" and COST[r["decision"]["card"]] == 1]
        stale = [r for r in conf if r["decision"].get("pressure_count", 0) and not r["cues"]["enemies"]]
        reasons = Counter(r["decision"]["reason"] for r in conf)
        result = {"session": session, **sessions[session], "completed":len(ends), "automatic_outcomes":dict(Counter(r["result"] for r in ends)), "cutoff": max(r["time"] for r in ends), "battle_minutes": duration/60, "attempts":len(plays), "confirmed":len(conf), "confirmation_rate":len(conf)/len(plays), "hog_count":sum(r["decision"]["card"]=="hog" for r in conf), "hogs_per_minute":sum(r["decision"]["card"]=="hog" for r in conf)*60/duration, "nominal_spend_by_category":dict(costs), "defense_spell_cost_share":(costs["defense"]+costs["spell"])/sum(costs.values()), "confirmed_card_category_counts":dict(Counter(r["decision"]["category"]+"/"+r["decision"]["card"] for r in conf)), "confirmed_reasons":dict(reasons), "observe_samples":len(obs), "full_elixir_samples":len(full), "full_elixir_clear_samples":sum(not r["cues"]["enemies"] for r in full), "full_elixir_examples":[compact(r) for r in full[:15]], "cheap_defense_attempts":len(cheap), "cheap_defense_confirmed":sum(r["confirmed"] for r in cheap), "cheap_defense_pressure_depths":dict(Counter(str(r["decision"].get("pressure_depth",0)//25*25) for r in cheap)), "held_pressure_defensive_plays":len(stale), "held_pressure_examples":[compact(r) for r in stale[:8]], "long_no_hog_spans":sorted(gaps,key=lambda g:(-g["defensive_nominal_cost"],-g["seconds"])), "combo_count":len(combos), "combo_hog_within7":sum(c["next_hog_seconds"] is not None and c["next_hog_seconds"]<=7 for c in combos), "combos":combos, "skill_attempts":len(skills), "skill_confirmed":sum(r["confirmed"] for r in skills), "skill_events":[compact(r) for r in skills], "late_card_replacement_after_unconfirmed_count":len(late_confirm), "late_card_replacement_examples":late_confirm[:15], "per_battle":per_battle}
        report["sessions"].append(result)
        print(json.dumps({k:result[k] for k in ("session","completed","automatic_outcomes","attempts","confirmed","hogs_per_minute","defense_spell_cost_share","full_elixir_samples","full_elixir_clear_samples","combo_count","combo_hog_within7","skill_attempts","skill_confirmed","cheap_defense_attempts","cheap_defense_confirmed","late_card_replacement_after_unconfirmed_count")},ensure_ascii=False))
    report["limitations"] = ["Outcomes are automatic labels, not independently verified game results; unknowns stay unknown.", "Nominal spend uses confirmed card cost, not exact measured elixir; regen and false confirmations may bias it.", "Observations are sampled about every 10 seconds when no decision occurs. No continuous leak-duration claim follows from their count.", "A no-Hog span does not itself prove a bad strategic choice; detailed pressure and hand evidence are supplied.", "Any screenshot/manual claim requires separate review; this audit does not operate the emulator."]
    (ROOT/"work/v3-trace-audit.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")


if __name__ == "__main__":
    main()
