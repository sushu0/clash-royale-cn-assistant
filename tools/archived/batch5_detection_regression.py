from pathlib import Path
import sys,json,cv2,numpy as np,time
ROOT=Path(r'D:\codex\CodexWork\clash');REP=ROOT/'py-clash-bot';sys.path.insert(0,str(REP))
from pyclashbot.detection.cn_battle_cues import read_cn_battle_cues
original=REP/'pyclashbot'/'detection'/'cn_battle_cues.py'
backup=ROOT/'work'/'backups'/'batch5-20260926-baseline'/'pyclashbot'/'detection'/'cn_battle_cues.py'
oldglobals={'__file__':str(original),'__name__':'cn_battle_cues_batch_baseline'};exec(compile(backup.read_text(encoding='utf8'),str(original),'exec'),oldglobals);oldread=oldglobals['read_cn_battle_cues']
BASE=ROOT/'work'/'batch5'/'20260926-1535-baseline';OUT=BASE/'vision_audit';files=sorted((ROOT/'work'/'hog-validation').glob('*/observe-*.png'))+sorted((ROOT/'work'/'hog-validation').glob('*/play-*.png'))+sorted((BASE/'evidence').glob('*.png'))
changes=[];other=0;start=time.perf_counter()
for p in files:
    f=cv2.imread(str(p));before=oldread(f);after=read_cn_battle_cues(f)
    if before['enemies']!=after['enemies']:changes.append({'file':str(p),'before':before['enemies'],'after':after['enemies'],'removed':[v for v in before['enemies']if v not in after['enemies']]})
    if any(before[k]!=after[k]for k in ('elixir','enemy_towers','elite_ability_ready')):other+=1
summary={'frames':len(files),'changed_enemy_frames':len(changes),'removed_markers':sum(len(r['removed'])for r in changes),'other_cues_changed':other,'seconds':round(time.perf_counter()-start,2)}
(OUT/'candidate-regression.json').write_text(json.dumps({'summary':summary,'changes':changes},indent=2),encoding='utf8')
removed=[(r['file'],v)for r in changes for v in r['removed']];s=np.full((int(np.ceil(len(removed)/10))*90,1000,3),245,np.uint8)
for i,(file,(x,y))in enumerate(removed):
    f=cv2.imread(file);p=f[max(0,y-31):y+9,max(0,x-20):x+20];p=cv2.resize(p,(75,75));xx=i%10*100;yy=i//10*90;s[yy:yy+75,xx:xx+75]=p;cv2.putText(s,str(i),(xx,yy+86),cv2.FONT_HERSHEY_SIMPLEX,.35,(0,0,0),1)
if removed:cv2.imwrite(str(OUT/'removed-marker-crops.jpg'),s)
print(json.dumps(summary,indent=2))
