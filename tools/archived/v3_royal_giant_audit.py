from pathlib import Path
import json,sys,cv2,numpy as np,hashlib,time
ROOT=Path(r'D:\codex\CodexWork\clash');sys.path.insert(0,str(ROOT/'py-clash-bot'))
from pyclashbot.detection.cn_battle_cues import read_cn_battle_cues
OUT=ROOT/'work'/'v3-royal-giant';OUT.mkdir(exist_ok=True);SRC=ROOT/'work'/'hog-validation'
source=SRC/'20260926-122831'/'observe-01-122911.png';b=source.read_bytes();(OUT/'source.png').write_bytes(b);digest=hashlib.sha256(b).hexdigest()
f=cv2.imdecode(np.frombuffer(b,np.uint8),cv2.IMREAD_COLOR);tpl=f[270:294,296:330];gray=cv2.cvtColor(tpl,cv2.COLOR_BGR2GRAY);cv2.imwrite(str(OUT/'rush_royal_giant_head.png'),tpl)
files=sorted(SRC.glob('*/observe-*.png'))+sorted(SRC.glob('*/play-*.png'));rows=[];scores=[];start=time.perf_counter()
for p in files:
    f=cv2.imread(str(p));enemies=read_cn_battle_cues(f)['enemies']
    for ex,ey in enemies:
        x1=max(0,ex+4-8);y1=max(0,ey-8-8);x2=min(419,ex+4+34+8);y2=min(510,ey-8+24+8);roi=f[y1:y2,x1:x2]
        if roi.shape[0]<24 or roi.shape[1]<34:continue
        c=cv2.matchTemplate(roi,tpl,cv2.TM_CCOEFF_NORMED);g=cv2.matchTemplate(cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY),gray,cv2.TM_CCOEFF_NORMED)
        _,score,_,(x,y)=cv2.minMaxLoc(np.minimum(c,g));scores.append(score)
        if score>=.65:rows.append({'file':str(p),'anchor':[ex,ey],'score':score,'bbox':[x+x1,y+y1,34,24]})
summary={'source':str(source),'source_sha256':digest,'frames':len(files),'candidate_count':len(rows),'seconds':time.perf_counter()-start}
(OUT/'candidates.json').write_text(json.dumps({'summary':summary,'candidates':rows},indent=2),encoding='utf8')
s=np.full((int(np.ceil(len(rows)/8))*115,1000,3),245,np.uint8)
for i,r in enumerate(rows):
    f=cv2.imread(r['file']);x,y,w,h=r['bbox'];p=cv2.resize(f[max(0,y-15):y+h+30,max(0,x-15):x+w+15],(100,90));xx=i%8*125;yy=i//8*115;s[yy:yy+90,xx:xx+100]=p;cv2.putText(s,f'{i}:{r["score"]:.3f}',(xx,yy+108),cv2.FONT_HERSHEY_SIMPLEX,.38,(0,0,0),1)
if rows:cv2.imwrite(str(OUT/'candidates.jpg'),s)
print(json.dumps(summary,indent=2));print([(i,Path(r['file']).parent.name,Path(r['file']).name,round(r['score'],3))for i,r in enumerate(rows)])
