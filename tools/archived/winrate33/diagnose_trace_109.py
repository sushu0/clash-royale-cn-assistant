"""Read-only retrospective metrics for the fixed 109-battle diagnostic window."""
from __future__ import annotations

import hashlib
import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
CUTOFF = "2026-09-27 00:05:53"
AFTER = "2026-09-26 18:12:03"
COST = {"hog": 4, "musketeer": 4, "cannon": 3, "fireball": 4,
        "ice_golem": 2, "log": 2, "ice_spirit": 1, "skeletons": 1}


def ts(value):
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").timestamp()


def distribution(values):
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    return {"n": len(values), "min": min(values), "median": statistics.median(values),
            "mean": statistics.mean(values), "p90": ordered[min(len(ordered)-1, int(.9*(len(ordered)-1)))], "max": max(values)}


def compact(row):
    return {key: row[key] for key in ("line", "time", "session", "battle", "event", "decision", "cues", "confirmed") if key in row}


def main():
    trace_path = ROOT / "outputs/cn-hog-strategy.jsonl"
    log_path = ROOT / "outputs/cn-battles-live.log"
    raw_trace, raw_log = trace_path.read_bytes(), log_path.read_bytes()
    trace = []
    for line, text in enumerate(raw_trace.decode("utf-8").splitlines(), 1):
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if AFTER < row.get("time", "") <= CUTOFF:
            row.update(line=line, ts=ts(row["time"]))
            trace.append(row)
    ends = [row for row in trace if row["event"] == "battle_end"]
    ends.sort(key=lambda row: row["time"])
    assert len(ends) == 109
    keys = {(row["session"], row["battle"]) for row in ends}
    assert len(keys) == 109
    rows = [row for row in trace if (row.get("session"), row.get("battle")) in keys]
    log_ends, log_starts, recoveries = [], defaultdict(list), []
    log_session, resumed = None, False
    for line, text in enumerate(raw_log.decode("utf-8").splitlines(), 1):
        if "连续对战已启动" in text:
            log_session = text[:19]
        if "接管已开始" in text:
            resumed = True
        match = re.search(r"对战开始 场次=(\d+)", text)
        if match:
            log_starts[log_session, int(match[1])].append({"time":text[:19], "line":line, "resumed":resumed})
            resumed = False
        match = re.search(r"对战结束 结果=(\S+) 出牌确认=(\d+)/(\d+) 已完成=(\d+)", text)
        if match and AFTER < text[:19] <= CUTOFF:
            log_ends.append({"time":text[:19], "session_start":log_session, "battle":int(match[4]),
                             "result":match[1], "confirmed":int(match[2]), "attempts":int(match[3]), "line":line})
        if AFTER < text[:19] <= CUTOFF and ("恢复/重启" in text or "恢复事件" in text):
            recoveries.append({"line":line,"text":text})
    by_battle = defaultdict(list)
    for row in rows:
        by_battle[row["session"], row["battle"]].append(row)
    plays = [row for row in rows if row["event"] == "play"]
    confirmed = [row for row in plays if row["confirmed"]]
    observe = [row for row in rows if row["event"] == "observe"]
    costs = Counter()
    for row in confirmed:
        costs[row["decision"]["category"]] += COST[row["decision"]["card"]]
    games, action_gaps, hog_gaps, no_hog, full_wait, combos, delayed = [], [], [], [], [], [], []
    for end in ends:
        key = end["session"], end["battle"]
        group = by_battle[key]
        matched = [item for item in log_ends if item["battle"] == end["battle"] and abs(ts(item["time"])-end["ts"]) <= 1]
        assert len(matched) == 1 and matched[0]["result"] == end["result"]
        starts = log_starts[matched[0]["session_start"], end["battle"]]
        before = [item for item in starts if item["time"] <= end["time"]]
        start = before[-1]
        beginning = ts(start["time"])
        gp = [row for row in group if row["event"] == "play"]
        gc = [row for row in gp if row["confirmed"]]
        hogs = [row for row in gc if row["decision"]["card"] == "hog"]
        attacks = [row for row in gc if row["decision"]["category"] == "attack"]
        gcost = Counter()
        for row in gc:
            gcost[row["decision"]["category"]] += COST[row["decision"]["card"]]
        first_hog = hogs[0] if hogs else None
        games.append({"session":key[0],"battle":key[1],"result":end["result"],"start":start["time"],"end":end["time"],
            "duration_seconds":end["ts"]-beginning,"log_end_line":matched[0]["line"],"trace_end_line":end["line"],
            "multiple_start_records":len(before),"resumed":start["resumed"],"attempts":len(gp),"confirmed":len(gc),
            "end_counters_match_trace":(len(gp),len(gc))==(end["attempts"],end["confirmed"]),
            "first_confirmed_card":gc[0]["decision"]["card"] if gc else None,
            "first_confirmed_delay":gc[0]["ts"]-beginning if gc else None,
            "first_attack_lane":("left" if attacks[0]["decision"]["point"][0]<209 else "right") if attacks else None,
            "first_hog_delay":first_hog["ts"]-beginning if first_hog else None,
            "first_hog_lane":("left" if first_hog["decision"]["point"][0]<209 else "right") if first_hog else None,
            "first_hog_elixir":first_hog["decision"]["elixir"] if first_hog else None,
            "first_hog_after_elixir":first_hog.get("after_elixir") if first_hog else None,
            "hog_count":len(hogs),"nominal_cost_by_category":dict(gcost),
            "defense_spell_cost_share":(gcost["defense"]+gcost["spell"])/sum(gcost.values()) if gcost else None,
            "first_hog_nearby_early_pressure_samples":sum(bool(row.get("cues",{}).get("enemies")) for row in group
                if first_hog and first_hog["ts"]<row["ts"]<=first_hog["ts"]+10),
            "first_hog_then_low_elixir_defense":sum(row["decision"]["category"] in ("defense","spell") and row["decision"]["elixir"]<=3
                for row in gc if first_hog and first_hog["ts"]<row["ts"]<=first_hog["ts"]+15)})
        action_gaps += [b["ts"]-a["ts"] for a,b in zip(gc,gc[1:])]
        hog_gaps += [b["ts"]-a["ts"] for a,b in zip(hogs,hogs[1:])]
        points = [beginning]+[row["ts"] for row in hogs]+[end["ts"]]
        for a,b in zip(points,points[1:]):
            if b-a < 45:
                continue
            inside = [row for row in group if a<row["ts"]<b]
            dp = [row for row in inside if row["event"]=="play" and row["confirmed"] and row["decision"]["category"] in ("defense","spell")]
            affordable = [row for row in inside if isinstance(row.get("cues",{}).get("elixir"),int) and row["cues"]["elixir"]>=6
                and any(hand.get("card")=="hog" and hand.get("available") for hand in row.get("hand",[]))]
            no_hog.append({"session":key[0],"battle":key[1],"seconds":b-a,"from":datetime.fromtimestamp(a).strftime('%Y-%m-%d %H:%M:%S'),
                "to":datetime.fromtimestamp(b).strftime('%Y-%m-%d %H:%M:%S'),"defensive_plays":len(dp),
                "defensive_nominal_cost":sum(COST[row["decision"]["card"]] for row in dp),"affordable_hog_samples":len(affordable),
                "affordable_examples":[compact(row) for row in affordable[:3]]})
        for index,row in enumerate(group):
            later = group[index+1:]
            if row["event"]=="observe" and row["cues"]["elixir"]==10:
                nxt = next((x for x in later if x["event"] in ("play","elite_ability")),None)
                full_wait.append({**compact(row),"hand":[x["card"] for x in row["hand"]],"next_action_delay":None if nxt is None else nxt["ts"]-row["ts"],
                                  "next_action":nxt.get("decision") if nxt else None})
            if row["event"]!="play":
                continue
            if row["confirmed"] and row["decision"]["card"]=="ice_golem" and row["decision"]["category"]=="attack":
                follow = next((x for x in later if x["event"]=="play" and x["confirmed"] and x["decision"]["card"]=="hog"),None)
                combos.append({"session":key[0],"battle":key[1],"time":row["time"],"next_hog_delay":follow["ts"]-row["ts"] if follow else None})
            if not row["confirmed"]:
                slot=row["decision"]["slot"]
                for nxt in later:
                    if nxt["ts"]-row["ts"]>12 or nxt["event"]=="battle_end":break
                    card=next((hand["card"] for hand in nxt.get("hand",[]) if hand["slot"]==slot),None)
                    if card and card!=row["decision"]["card"]:
                        delayed.append({"session":key[0],"battle":key[1],"time":row["time"],"card":row["decision"]["card"],"line":row["line"],"next_card":card,"delay":nxt["ts"]-row["ts"]});break
                    if nxt["event"]=="play" and nxt["decision"]["slot"]==slot:break
    seconds=sum(game["duration_seconds"] for game in games)
    cards={card:{"attempts":sum(row["decision"]["card"]==card for row in plays),"confirmed":sum(row["decision"]["card"]==card for row in confirmed)} for card in COST}
    for counts in cards.values():counts["confirmation_rate"]=counts["confirmed"]/counts["attempts"] if counts["attempts"] else None
    availability = []
    for end in ends:
        evidence=end.get("evidence") or {};path=Path(evidence.get("path",""));data=path.read_bytes() if path.is_file() else None
        availability.append({"session":end["session"],"battle":end["battle"],"result":end["result"],"time":end["time"],
            "path":str(path),"expected_sha256":evidence.get("sha256"),"verified_now":data is not None and hashlib.sha256(data).hexdigest()==evidence.get("sha256"),"bytes":len(data) if data else None})
    manifests={session:json.loads((ROOT/'work/hog-validation'/session/'policy-manifest.json').read_text(encoding='utf-8')) for session in sorted({row['session'] for row in ends})}
    report={"scope":{"after":AFTER,"cutoff_inclusive":CUTOFF,"completed_games":len(ends),"trace_sha256_read_snapshot":hashlib.sha256(raw_trace).hexdigest(),"log_sha256_read_snapshot":hashlib.sha256(raw_log).hexdigest(),
        "note":"Fixed same 109-game window as the preceding win-rate check; later games are excluded. Diagnosis, not another favorable sample selection."},
        "runtime_manifests":manifests,"same_runtime_sources_and_assets":len({json.dumps(m,sort_keys=True) for m in manifests.values()})==1,
        "session_counts":dict(Counter(row['session'] for row in ends)),"results_context_only":dict(Counter(row['result'] for row in ends)),"battle_minutes":seconds/60,
        "attempts":len(plays),"confirmed":len(confirmed),"confirmation_rate":len(confirmed)/len(plays),"confirmed_actions_per_minute":len(confirmed)*60/seconds,
        "cards":cards,"nominal_cost_by_category":dict(costs),"nominal_cost_share_by_category":{key:value/sum(costs.values()) for key,value in costs.items()},
        "nominal_cost_per_minute":sum(costs.values())*60/seconds,"defense_spell_share":(costs['defense']+costs['spell'])/sum(costs.values()),
        "confirmed_reasons":dict(Counter(row['decision']['reason'] for row in confirmed)),"confirmed_card_category_counts":dict(Counter(row['decision']['category']+'/'+row['decision']['card'] for row in confirmed)),
        "confirmed_action_intervals_seconds":distribution(action_gaps),"hog_intervals_seconds":distribution(hog_gaps),"hog_per_minute":cards['hog']['confirmed']*60/seconds,
        "first_hog_delay_seconds":distribution([game['first_hog_delay'] for game in games if game['first_hog_delay'] is not None]),
        "first_card_counts":dict(Counter(game['first_confirmed_card'] for game in games)),"first_hog_lane_counts":dict(Counter(str(game['first_hog_lane']) for game in games)),
        "first_attack_lane_counts":dict(Counter(str(game['first_attack_lane']) for game in games)),"all_hog_lane_counts":dict(Counter('left' if row['decision']['point'][0]<209 else 'right' for row in confirmed if row['decision']['card']=='hog')),
        "first_hog_elixir_counts":dict(Counter(str(game['first_hog_elixir']) for game in games)),"first_hog_after_elixir_counts":dict(Counter(str(game['first_hog_after_elixir']) for game in games)),
        "openers_followed_by_low_elixir_defense":sum(bool(game['first_hog_then_low_elixir_defense']) for game in games),
        "no_hog_intervals_at_least45":sorted(no_hog,key=lambda x:-x['seconds']),"observe_samples":len(observe),"unknown_elixir_observe_samples":sum(row['cues']['elixir'] is None for row in observe),
        "full_elixir_samples":len(full_wait),"full_elixir_clear_samples":sum(not row['cues']['enemies'] for row in full_wait),"full_elixir_wait_examples":sorted(full_wait,key=lambda x:x['next_action_delay'] or 0,reverse=True),
        "combo_leads":len(combos),"combo_followup_within7":sum(row['next_hog_delay'] is not None and row['next_hog_delay']<=7 for row in combos),"combos":combos,
        "unconfirmed_later_same_slot_replacement":len(delayed),"late_replacement_examples":delayed[:20],
        "typed_observation_events":sum(bool(row.get('cues',{}).get('threats')) for row in rows),"typed_action_attempts":sum(bool(row['decision'].get('threat_kind')) for row in plays),
        "skills":{"attempts":sum(row['event']=='elite_ability' for row in rows),'confirmed':sum(row.get('confirmed',False) for row in rows if row['event']=='elite_ability')},
        "recoveries":recoveries,"games":games,"result_evidence_availability":availability,
        "result_images_currently_verified":sum(row['verified_now'] for row in availability),"unknown_results_for_mandatory_review":[row for row in availability if row['result']=='未知'],
        "limitations":["Confirmed deployment is a hand/elixir observation, not measured damage, correct targeting or tactical effectiveness.","Costs are nominal per confirmed card; ability spend is separate, and regeneration obscures exact measured spend.","Observe records are sparse (about 10 seconds while idle); samples do not measure continuous waiting or exact elixir leakage.","Log battle starts are observed-state starts; resumed/incomplete prior activity, if any, must be inspected separately.","Only two wins in this window; outcome-group differences cannot establish causal strategy effects."]}
    OUT.mkdir(exist_ok=True)
    (OUT/'trace-diagnosis.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:report[key] for key in ('session_counts','same_runtime_sources_and_assets','battle_minutes','attempts','confirmed','confirmation_rate','confirmed_actions_per_minute','nominal_cost_by_category','nominal_cost_share_by_category','nominal_cost_per_minute','hog_per_minute','hog_intervals_seconds','first_hog_delay_seconds','first_hog_lane_counts','first_hog_elixir_counts','openers_followed_by_low_elixir_defense','full_elixir_samples','full_elixir_clear_samples','unknown_elixir_observe_samples','combo_leads','combo_followup_within7','unconfirmed_later_same_slot_replacement','typed_observation_events','typed_action_attempts','skills','result_images_currently_verified')},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
