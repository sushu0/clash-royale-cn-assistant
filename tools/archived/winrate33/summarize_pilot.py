"""Compact read-only pilot metrics from frozen collector evidence."""
import argparse
import hashlib
import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from trial_ledger import disk_version_issues

ROOT = Path(__file__).resolve().parents[2]
COSTS = {"hog":4,"musketeer":4,"cannon":3,"fireball":4,"ice_golem":2,"log":2,"ice_spirit":1,"skeletons":1}


def stamp(value):
    return datetime.strptime(value,"%Y-%m-%d %H:%M:%S").timestamp()


def stats(values):
    ordered=sorted(values)
    return {"n":len(ordered),"median":statistics.median(ordered),"p90":ordered[int(.9*(len(ordered)-1))],"mean":statistics.mean(ordered),"max":max(ordered)} if ordered else {"n":0}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-dir",required=True,type=Path)
    args=parser.parse_args()
    folder=args.pilot_dir.resolve();folder.relative_to((ROOT/'work/winrate33').resolve())
    status=json.loads((folder/'capture-status.json').read_text(encoding='utf-8'))
    events=[json.loads(line) for line in (folder/'events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    starts={row['battle']:row for row in events if row['event']=='battle_start'}
    ends=[row for row in events if row['event']=='battle_end'];completed={row['battle'] for row in ends}
    rows=[row for row in events if row.get('battle') in completed]
    plays=[row for row in rows if row['event']=='play'];confirmed=[row for row in plays if row['confirmed']]
    cost=Counter();timings=defaultdict(list)
    for row in confirmed:cost[row['decision']['category']]+=COSTS[row['decision']['card']]
    for row in plays:
        for kind,value in row.get('timing_ms',{}).items():timings[kind].append(value)
    games=[];combos=[]
    for end in ends:
        group=[row for row in rows if row['battle']==end['battle']]
        cp=[row for row in group if row['event']=='play' and row['confirmed']]
        hogs=[row for row in cp if row['decision']['card']=='hog']
        games.append({'battle':end['battle'],'start':starts[end['battle']]['time'],'resumed':starts[end['battle']].get('resumed'),
            'end':end['time'],'result':end['result'],'confirmed':end['confirmed'],'attempts':end['attempts'],
            'seconds':stamp(end['time'])-stamp(starts[end['battle']]['time']),'hog_count':len(hogs),
            'first_hog_lane':('left' if hogs[0]['decision']['point'][0]<209 else 'right') if hogs else None})
        for index,row in enumerate(cp):
            if row['decision']['card']=='ice_golem' and row['decision']['category']=='attack':
                follow=next((item for item in cp[index+1:] if item['decision']['card']=='hog'),None)
                combos.append({'battle':end['battle'],'time':row['time'],'hog_delay':stamp(follow['time'])-stamp(row['time']) if follow else None})
    seconds=sum(row['seconds'] for row in games);hog_count=sum(row['hog_count'] for row in games)
    proofs=[]
    logs=[json.loads(line) for line in (folder/'battle-log.jsonl').read_text(encoding='utf-8').splitlines()]
    next_starts={}
    for item in logs:
        match=re.search(r'对战开始 场次=(\d+)',item['text'])
        if match:next_starts[int(match[1])]=item['text'][:19]
    final=next((row for row in events if row['event']=='batch_complete'),None)
    for end in ends:
        next_time=next_starts.get(end['battle']+1) if end['battle']<status['last_battle'] else final.get('time') if final else None
        proofs.append({'battle':end['battle'],'boundary':'next_battle' if end['battle']<status['last_battle'] else 'final_lobby',
                       'boundary_time':next_time,'seconds_after_end':stamp(next_time)-stamp(end['time']) if next_time else None})
    hashes={};references=0
    for row in events:
        for evidence in row.get('captured_evidence',{}).values():
            references+=1
            if evidence.get('frozen_path'):hashes[evidence['expected_sha256']]=evidence['frozen_path']
    bad=[sha for sha,path in hashes.items() if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=sha]
    manifest=json.loads((folder/'policy-manifest.json').read_text(encoding='utf-8'))
    reviews=json.loads((folder/'result-reviews.json').read_text(encoding='utf-8')) if (folder/'result-reviews.json').is_file() else []
    rewards=[row for row in events if row['event']=='reward'];recoveries=[row for row in events if row['event']=='recovery']
    pid=json.loads((ROOT/'work/bot-processes.json').read_text(encoding='utf-8'))
    normal_exit=bool(final and pid.get('exit_reason')=='finite_run_ended' and pid.get('max_battles')==status['last_battle']
                     and 0<=stamp(pid['ended_at'])-stamp(final['time'])<=60)
    report={'session':status['session'],'pilot_only':True,'formal_100_trial_started':False,'created_at':datetime.now().isoformat(timespec='seconds'),
        'completed':len(ends),'results_auto':dict(Counter(row['result'] for row in ends)),'result_reviews':reviews,
        'confirmed':len(confirmed),'attempts':len(plays),'confirmation_rate':len(confirmed)/len(plays) if plays else None,
        'battle_minutes':seconds/60,'hog_count':hog_count,'hog_per_minute':hog_count*60/seconds if seconds else None,
        'nominal_cost_by_category':dict(cost),'nominal_cost_share':{key:value/sum(cost.values()) for key,value in cost.items()},
        'timing_ms':{key:stats(values) for key,values in timings.items()},'timing_note':'Producer instrumentation covers decision/deploy/confirmation; this is not the full screenshot-to-next-loop interval.',
        'ice_golem_attack_leads':len(combos),'hog_followups_within7s':sum(row['hog_delay'] is not None and row['hog_delay']<=7 for row in combos),
        'hog_combos':combos,'attack_ice_spirit_confirmed':sum(row['decision']['card']=='ice_spirit' and row['decision']['category']=='attack' for row in confirmed),
        'games':games,'flow_boundaries':proofs,'reward_events':len(rewards),'recoveries':recoveries,'batch_complete':final,
        'evidence':{'events':len(events),'references':references,'unique_pngs':len(hashes),'hash_bad':bad,'missing':status['missing_evidence_count']},
        'runtime_manifest':manifest,'disk_version_issues':disk_version_issues(manifest),'source_count':len(manifest['source_sha256']),'asset_count':len(manifest['asset_sha256']),
        'manifest_matches_log':status.get('verified_log_session_binding',{}).get('source_hashes_match'),
        'normal_exit_marker':normal_exit,'pid_manifest_snapshot':pid,'unexpected_next_start':status.get('unexpected_next_start_in_lobby_mode'),
        'collector_complete':status['status']=='complete','limitations':['Five pilot games do not satisfy the fixed 100-game/33-independently-confirmed-win target.','Confirmed deployment is not proof of tactical effectiveness or tower damage.']}
    (folder/'pilot-summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:report[key] for key in ('session','completed','results_auto','confirmed','attempts','hog_count','hog_per_minute','nominal_cost_share','timing_ms','ice_golem_attack_leads','hog_followups_within7s','attack_ice_spirit_confirmed','evidence','normal_exit_marker','disk_version_issues')},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
