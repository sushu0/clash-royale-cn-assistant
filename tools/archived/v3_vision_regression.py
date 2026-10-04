from pathlib import Path
import json,sys,cv2,time
ROOT=Path(r'D:\codex\CodexWork\clash');sys.path.insert(0,str(ROOT/'py-clash-bot'))
from pyclashbot.detection.cn_battle_cues import read_cn_battle_cues
OUT=ROOT/'work'/'v3-vision-audit'
old=json.loads((OUT/'baseline-all.json').read_text());rows=[];start=time.perf_counter()
for file,before in old.items():
    after=read_cn_battle_cues(cv2.imread(file))
    missing=[pt for pt in before['enemies']if not any(abs(pt[0]-x)<=7 and abs(pt[1]-y)<=7 for x,y in after['enemies'])]
    added=[pt for pt in after['enemies']if not any(abs(pt[0]-x)<=7 and abs(pt[1]-y)<=7 for x,y in before['enemies'])]
    rows.append({'file':file,'before':before,'after':after,'missing':missing,'added':added})
latest=[r for r in rows if '20260926-005724'in r['file']and'\\observe-'in r['file']]
summary={'frames':len(rows),'seconds':round(time.perf_counter()-start,2),'elixir_unchanged':all(r['before']['elixir']==r['after']['elixir']for r in rows),'tower_unchanged':all(r['before']['enemy_towers']==r['after']['enemy_towers']for r in rows),'ability_unchanged':all(r['before']['elite_ability_ready']==r['after']['elite_ability_ready']for r in rows),'missing_old_markers':sum(len(r['missing'])for r in rows),'missing_details':[r for r in rows if r['missing']],'new_markers':sum(len(r['added'])for r in rows),'latest_frames':len(latest),'latest_added':sum(len(r['added'])for r in latest),'latest_empty_before':sum(not r['before']['enemies']for r in latest),'latest_empty_after':sum(not r['after']['enemies']for r in latest)}
(OUT/'regression.json').write_text(json.dumps({'summary':summary,'records':rows},indent=2),encoding='utf8')
print(json.dumps(summary,indent=2))
