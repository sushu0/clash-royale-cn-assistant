from pathlib import Path
import json,sys,cv2,numpy as np
ROOT=Path(r'D:\codex\CodexWork\clash');REP=ROOT/'py-clash-bot';sys.path.insert(0,str(REP));OUT=ROOT/'work'/'batch5'/'20260926-1535-baseline'/'vision_audit';p=REP/'pyclashbot'/'detection'/'cn_battle_cues.py'
ns={'__file__':str(p),'__name__':'refine_gate'};exec(compile(p.read_text().replace('similarity < 0.40','label_width <= 8 and similarity < 0.20'),str(p),'exec'),ns)
prior=json.loads((OUT/'candidate-regression.json').read_text());records=[]
for r in prior['changes']:
    f=cv2.imread(r['file']);now=ns['read_cn_battle_cues'](f)['enemies'];removed=[pt for pt in r['before']if tuple(pt) not in now]
    if removed:records.append({'file':r['file'],'before':r['before'],'after':now,'removed':removed})
flat=[(r['file'],pt)for r in records for pt in r['removed']];sheet=np.full((int(np.ceil(len(flat)/8))*110,8*125,3),245,np.uint8)
for i,(file,(x,y))in enumerate(flat):
    f=cv2.imread(file);crop=f[max(0,y-31):y+9,max(0,x-20):x+20].copy();cv2.drawMarker(crop,(20,15),(0,255,255),cv2.MARKER_CROSS,8,1);tile=cv2.resize(crop,(100,100),interpolation=cv2.INTER_NEAREST);xx=i%8*125;yy=i//8*110;sheet[yy:yy+100,xx:xx+100]=tile;cv2.putText(sheet,str(i),(xx,yy+109),cv2.FONT_HERSHEY_SIMPLEX,.3,(0,0,0),1)
if flat:cv2.imwrite(str(OUT/'repair-gate020-removed.jpg'),sheet)
(OUT/'repair-gate020.json').write_text(json.dumps(records,indent=2),encoding='utf8');print(json.dumps({'frames':len(records),'removed':len(flat)},indent=2))
