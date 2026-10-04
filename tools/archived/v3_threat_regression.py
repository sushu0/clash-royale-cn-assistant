from pathlib import Path
import sys,cv2,json,time,hashlib,numpy as np
ROOT=Path(r'D:\codex\CodexWork\clash');sys.path.insert(0,str(ROOT/'py-clash-bot'))
from pyclashbot.detection.cn_battle_cues import read_cn_battle_cues
from pyclashbot.detection.cn_threats import read_cn_threats
OUT=ROOT/'work'/'v3-threats'
files=sorted((ROOT/'work'/'hog-validation').glob('*/observe-*.png'))+sorted((ROOT/'work'/'hog-validation').glob('*/play-*.png'))+sorted((OUT/'source').glob('recent-play-before-*.png'))
hits=[];n=0;start=time.perf_counter()
for p in files:
    f=cv2.imread(str(p))
    if f is None:continue
    n+=1;e=read_cn_battle_cues(f)['enemies'];h=read_cn_threats(f,e)
    if h:hits.append({'file':str(p),'threats':h})
summary={'scanned_frames':n,'matched_frames':len(hits),'seconds':round(time.perf_counter()-start,2),'enabled_subtypes':['air_skeleton_barrel_top'],'unsupported_classes':['rush','swarm'],'threshold':0.74,'minimum_red_fraction':0.55,'source_self_match':'20260926-005724/observe-01-005913.png','independent_positive_sources':['20260925-145226/observe-05-150337.png','20260925-181459/observe-02-182034.png'],'known_different_pose_unknown':'20260925-172029/observe-03-172710.png','not_a_probability':True,'module_sha256':hashlib.sha256((ROOT/'py-clash-bot'/'pyclashbot'/'detection'/'cn_threats.py').read_bytes()).hexdigest()}
(OUT/'regression.json').write_text(json.dumps({'summary':summary,'hits':hits},indent=2),encoding='utf8')
flat=[(r['file'],h)for r in hits for h in r['threats']]
if flat:
    s=np.full((int(np.ceil(len(flat)/8))*115,1000,3),245,np.uint8)
    for i,(file,h)in enumerate(flat):
        f=cv2.imread(file);x,y,w,hh=h['sprite_bbox'];p=cv2.resize(f[max(0,y-18):y+hh+22,max(0,x-12):x+w+12],(100,90));xx=i%8*125;yy=i//8*115;s[yy:yy+90,xx:xx+100]=p;cv2.putText(s,f'{i}:{h["confidence"]:.3f}',(xx,yy+108),cv2.FONT_HERSHEY_SIMPLEX,.38,(0,0,0),1)
    cv2.imwrite(str(OUT/'enabled-matches.jpg'),s)
print(json.dumps(summary,indent=2))
