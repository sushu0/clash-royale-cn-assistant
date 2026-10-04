from pathlib import Path
import json,cv2,sys,numpy as np,hashlib,time
ROOT=Path(r'D:\codex\CodexWork\clash');REP=ROOT/'py-clash-bot';sys.path.insert(0,str(REP))
from pyclashbot.detection.cn_battle_cues import read_cn_battle_cues
BASE=ROOT/'work'/'batch5'/'20260926-170957-candidate2';OUT=BASE/'vision_audit';rows=json.loads((OUT/'map.json').read_text(encoding='utf8'));checked=0;diff=[];added=[];start=time.perf_counter()
for r in rows:
    before=r['data'].get('cues')
    if before is None:continue
    after=read_cn_battle_cues(cv2.imread(r['file']));checked+=1;missing=[p for p in before['enemies']if tuple(p)not in after['enemies']]
    if missing or any(before[k]!=after[k]for k in('elixir','enemy_towers','elite_ability_ready','threats')):diff.append({'i':r['i'],'missing':missing})
    extra=[p for p in after['enemies']if list(p)not in before['enemies']]
    if extra:added.append({'i':r['i'],'battle':r['battle'],'file':r['file'],'before':before['enemies'],'after':after['enemies'],'added':extra})
summary={'checked_primary_cue_frames':checked,'old_markers_or_other_cue_regressions':diff,'added_frames':len(added),'added_markers':sum(len(r['added'])for r in added),'seconds':round(time.perf_counter()-start,2),'cues_sha256':hashlib.sha256((REP/'pyclashbot'/'detection'/'cn_battle_cues.py').read_bytes()).hexdigest()}
(OUT/'gold-regression.json').write_text(json.dumps({'summary':summary,'frames':added},indent=2),encoding='utf8');print(json.dumps(summary,indent=2))
