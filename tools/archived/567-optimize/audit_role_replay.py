from pathlib import Path
import hashlib,json,sys
import cv2,numpy as np
ROOT=Path(r'D:\codex\CodexWork\clash');REPO=ROOT/'py-clash-bot';OUT=ROOT/'work/567-optimize/vision'
sys.path.insert(0,str(REPO))
from pyclashbot.detection.cn_threats import read_cn_threats
paths=[*OUT.glob('[0-9a-f]'*64+'.png'),*list((REPO/'tests/fixtures').rglob('*.png'))]
seen=set();hits=[];checked=0
for p in paths:
 data=p.read_bytes();sha=hashlib.sha256(data).hexdigest()
 if sha in seen:continue
 seen.add(sha);frame=cv2.imread(str(p))
 if frame is None or frame.shape!=(633,419,3):continue
 checked+=1; roles=[r for r in read_cn_threats(frame,[],include_567=True) if r.get('origin')=='567_role']
 if roles:hits.append({'path':str(p),'sha256':sha,'roles':roles})
report={'checked_unique_full_frames':checked,'frames_with_567_roles':len(hits),'hits':hits,
 'limits':['Only calibrated frontal baby dragon and drilling ground torso poses are enabled.',
           'Ground drill has one independent capture 2 seconds from source by event timestamps; this is not broad cross-battle validation.',
           'The trial ordinary/large Giant and Giant Skeleton crops failed independent similarity checks and were not installed.',
           'No card-complete unit classifier, no win-rate claim, no support for arbitrary flying or ground units.']}
(OUT/'role-replay-audit.json').write_text(json.dumps(report,indent=2),encoding='utf8')
tiles=[]
for row in hits:
 im=cv2.imread(row['path']);board=im[185:490].copy()
 for r in row['roles']:
  x,y,w,h=r['sprite_bbox'];cv2.rectangle(board,(x,y-185),(x+w,y+h-185),(0,255,255),1)
  cv2.circle(board,(r['x'],r['y']-185),4,(0,0,255),1)
 tile=np.zeros((345,419,3),np.uint8);tile[40:]=board
 txt='/'.join(r['kind']+':'+str(r['confidence']) for r in row['roles'])
 cv2.putText(tile,txt,(3,15),0,.45,(255,255,255),1);cv2.putText(tile,row['sha256'][:16],(3,33),0,.4,(255,255,255),1);tiles.append(tile)
if tiles:
 while len(tiles)%4:tiles.append(np.zeros_like(tiles[0]))
 cv2.imwrite(str(OUT/'role-replay-positives.png'),np.vstack([np.hstack(tiles[i:i+4]) for i in range(0,len(tiles),4)]))
print(json.dumps({k:v for k,v in report.items() if k!='hits'}))
