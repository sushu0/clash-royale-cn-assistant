from pathlib import Path
import json,sys,cv2,numpy as np,hashlib,time
ROOT=Path(r'D:\codex\CodexWork\clash');sys.path.insert(0,str(ROOT/'py-clash-bot'))
from pyclashbot.detection.cn_battle_cues import read_cn_battle_cues
BASE=ROOT/'work'/'batch5'/'20260926-1535-baseline';OUT=BASE/'vision_audit';files=sorted((ROOT/'work'/'hog-validation').glob('*/observe-*.png'))+sorted((ROOT/'work'/'hog-validation').glob('*/play-*.png'))+sorted((BASE/'evidence').glob('*.png'))
seen=set();hits=[];n=0;start=time.perf_counter()
for p in files:
    b=p.read_bytes();sha=hashlib.sha256(b).hexdigest()
    if sha in seen:continue
    seen.add(sha);f=cv2.imdecode(np.frombuffer(b,np.uint8),cv2.IMREAD_COLOR);n+=1;c=read_cn_battle_cues(f);h=[t for t in c['threats']if t['template_id']=='air_balloon_envelope']
    if h:hits.append({'file':str(p),'sha256':sha,'hits':h})
summary={'unique_frames':n,'matched_frames':len(hits),'threshold':.78,'min_red_fraction':.60,'seconds':round(time.perf_counter()-start,2)}
(OUT/'balloon-regression.json').write_text(json.dumps({'summary':summary,'matches':hits},indent=2),encoding='utf8')
flat=[(r['file'],h)for r in hits for h in r['hits']];s=np.full((int(np.ceil(len(flat)/8))*110,1000,3),245,np.uint8)
for i,(file,h)in enumerate(flat):
    f=cv2.imread(file);x,y,w,hh=h['sprite_bbox'];p=cv2.resize(f[max(0,y-12):y+hh+18,max(0,x-10):x+w+10],(100,90));xx=i%8*125;yy=i//8*110;s[yy:yy+90,xx:xx+100]=p;cv2.putText(s,f'{i}:{h["confidence"]:.3f}',(xx,yy+107),cv2.FONT_HERSHEY_SIMPLEX,.38,(0,0,0),1)
if flat:cv2.imwrite(str(OUT/'balloon-matched-crops.jpg'),s)
print(json.dumps(summary,indent=2))
