from pathlib import Path
import sys,json,cv2,numpy as np
ROOT=Path(r'D:\codex\CodexWork\clash');sys.path.insert(0,str(ROOT/'py-clash-bot'))
from pyclashbot.detection.cn_battle_cues import _gold_level_plaques
BASE=ROOT/sys.argv[1];OUT=BASE/'vision_audit';rows=json.loads((OUT/'map.json').read_text(encoding='utf8'));gold=[];air=[]
for r in rows:
    cues=r['data'].get('cues')
    if cues is None:continue
    f=cv2.imread(r['file']);hits=_gold_level_plaques(f,cv2.cvtColor(f,cv2.COLOR_BGR2HSV))
    if hits:gold.append({'i':r['i'],'time':r['time'],'battle':r['battle'],'file':r['file'],'raw_label_centers':hits,'live_enemies':cues['enemies']})
    typed=[t for t in cues.get('threats',[])if t['kind']=='air']
    if typed:air.append({'i':r['i'],'time':r['time'],'battle':r['battle'],'file':r['file'],'threats':typed})
summary={'gold_candidate_frames':len(gold),'air_typed_frames':len(air),'early_air_frames':sum(any(t.get('origin')=='early_air'for t in r['threats'])for r in air),'note':'Detector candidate counts require separate visual adjudication; they are not ground truth.'}
(OUT/'feature-coverage.json').write_text(json.dumps({'summary':summary,'gold_candidates':gold,'air_live':air},indent=2),encoding='utf8')
flat=[(r['i'],r['file'],p)for r in gold for p in r['raw_label_centers']];sheet=np.full((max(1,int(np.ceil(len(flat)/10)))*90,1000,3),245,np.uint8)
for k,(i,file,(x,y))in enumerate(flat):
    f=cv2.imread(file);p=cv2.resize(f[max(0,y-9):y+23,max(0,x-12):x+18],(75,70),interpolation=cv2.INTER_NEAREST);xx=k%10*100;yy=k//10*90;sheet[yy:yy+70,xx:xx+75]=p;cv2.putText(sheet,f'{k}:{i}',(xx,yy+85),cv2.FONT_HERSHEY_SIMPLEX,.35,(0,0,0),1)
if flat:cv2.imwrite(str(OUT/'gold-live-candidates.jpg'),sheet)
print(json.dumps(summary,indent=2))
