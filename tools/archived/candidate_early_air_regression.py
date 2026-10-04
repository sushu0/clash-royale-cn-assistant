from pathlib import Path
import json,sys,cv2,numpy as np,hashlib,time
ROOT=Path(r'D:\codex\CodexWork\clash');sys.path.insert(0,str(ROOT/'py-clash-bot'))
from pyclashbot.detection.cn_battle_cues import read_cn_battle_cues
BASE=ROOT/'work'/'batch5'/'20260926-161656-candidate';OUT=BASE/'vision_audit';rows=json.loads((OUT/'map.json').read_text(encoding='utf8'));checked=0;differences=[];hits=[];start=time.perf_counter()
for r in rows:
    before=r['data'].get('cues')
    if before is None:continue
    f=cv2.imread(r['file']);after=read_cn_battle_cues(f);checked+=1
    missing=[p for p in before['enemies']if tuple(p)not in after['enemies']]
    if missing or any(before[k]!=after[k]for k in ('elixir','enemy_towers','elite_ability_ready')):differences.append({'i':r['i'],'missing':missing})
    early=[t for t in after['threats']if t.get('origin')=='early_air']
    if early:hits.append({'i':r['i'],'time':r['time'],'file':r['file'],'early':early})
fingerprints={name:hashlib.sha256((ROOT/'py-clash-bot'/name).read_bytes()).hexdigest()for name in ('pyclashbot/detection/cn_battle_cues.py','pyclashbot/detection/cn_threats.py','pyclashbot/detection/reference_images/cn_threats/manifest.json')}
summary={'checked_primary_cue_frames':checked,'old_marker_or_other_cue_regressions':differences,'early_air_frames':len(hits),'seconds':round(time.perf_counter()-start,2),'fingerprints':fingerprints}
(OUT/'early-air-regression.json').write_text(json.dumps({'summary':summary,'matches':hits},indent=2),encoding='utf8')
flat=[(r['i'],r['file'],h)for r in hits for h in r['early']];s=np.full((int(np.ceil(len(flat)/8))*110,1000,3),245,np.uint8)
for j,(i,file,h)in enumerate(flat):
    f=cv2.imread(file);x,y,w,hh=h['sprite_bbox'];p=cv2.resize(f[max(0,y-16):y+hh+20,max(0,x-12):x+w+12],(100,90));xx=j%8*125;yy=j//8*110;s[yy:yy+90,xx:xx+100]=p;cv2.putText(s,f'{i}:{h["confidence"]:.3f}',(xx,yy+106),cv2.FONT_HERSHEY_SIMPLEX,.37,(0,0,0),1)
if flat:cv2.imwrite(str(OUT/'early-air-added.jpg'),s)
print(json.dumps(summary,indent=2))
