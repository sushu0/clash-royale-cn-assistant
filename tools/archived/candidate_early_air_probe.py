from pathlib import Path
import json,cv2,sys
ROOT=Path(r'D:\codex\CodexWork\clash');REP=ROOT/'py-clash-bot';sys.path.insert(0,str(REP))
from pyclashbot.detection.cn_threats import read_cn_threats
BASE=ROOT/'work'/'batch5'/'20260926-161656-candidate';OUT=BASE/'vision_audit';records=json.loads((OUT/'map.json').read_text(encoding='utf8'))
source=REP/'pyclashbot'/'detection'/'cn_battle_cues.py';ns={'__file__':str(source),'__name__':'early_air_probe'};exec(compile(source.read_text(encoding='utf8'),str(source),'exec'),ns);ns['CN_HOG_DEFENSE_ROI']=(43,185,377,270)
found=[]
for r in records:
    if r['event']not in ('observe','play'):continue
    f=cv2.imread(r['file']);early=ns['_read_enemy_pressure'](f);typed=[x for x in read_cn_threats(f,early)if x['kind']=='air'and x['template_id']=='air_balloon_envelope']
    if typed:found.append({'i':r['i'],'time':r['time'],'battle':r['battle'],'file':r['file'],'before_enemies':r['data'].get('cues',{}).get('enemies',[]),'early_candidates':early,'confirmed_early_air':typed})
(OUT/'early-air-probe.json').write_text(json.dumps(found,indent=2),encoding='utf8');print(json.dumps([{k:v for k,v in r.items()if k not in('file','early_candidates')}for r in found],indent=2))
