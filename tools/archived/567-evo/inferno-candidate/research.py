"""Offline Inferno Dragon reset investigation; no runtime imports or changes."""
from pathlib import Path
import json,hashlib,cv2,numpy as np
ROOT=Path(r'D:\codex\CodexWork\clash');OUT=Path(__file__).parent;OUT.mkdir(exist_ok=True)
SRC=ROOT/'work/567-validation/20260928-155830/play-10-bomber-before.png'
source_data=SRC.read_bytes();source_sha=hashlib.sha256(source_data).hexdigest();(OUT/(source_sha+'.png')).write_bytes(source_data)
events=[]
for log in [ROOT/'outputs/cn-567-strategy.jsonl']:
 for line in log.read_text(encoding='utf8').splitlines():
  try:e=json.loads(line)
  except json.JSONDecodeError:continue
  events.append(e)
source_refs=[];verified={}
for e in events:
 for field in ('evidence','evidence_before','evidence_after'):
  ref=e.get(field,{})
  if ref.get('sha256')==source_sha:source_refs.append({'time':e.get('time'),'battle':e.get('battle'),'session':e.get('session'),'field':field,**ref})
  p=Path(ref.get('path',''))
  if not p.is_file() or p.suffix.lower()!='.png':continue
  data=p.read_bytes();sha=hashlib.sha256(data).hexdigest()
  if sha!=ref.get('sha256') or sha in verified:continue
  dest=OUT/(sha+'.png');dest.write_bytes(data)
  verified[sha]={'time':e.get('time'),'battle':e.get('battle'),'session':e.get('session'),'field':field,'frozen_path':str(dest),'original_path':str(p),'sha256':sha}
(OUT/'verified.json').write_text(json.dumps({'source_sha256':source_sha,'source_trace_refs':source_refs,'frames':list(verified.values())},indent=2),encoding='utf8')
print('source',source_sha,source_refs,'verified',len(verified),flush=True)
src=cv2.imread(str(SRC)); crop=(76,244,98,267);x1,y1,x2,y2=crop;t=src[y1:y2,x1:x2];gray=cv2.cvtColor(t,cv2.COLOR_BGR2GRAY)
cv2.imwrite(str(OUT/'helmet_green_source_candidate.png'),t)
paths=list(OUT.glob('[0-9a-f]'*64+'.png'))+list((ROOT/'work/567-optimize/vision').glob('[0-9a-f]'*64+'.png'))+list((ROOT/'py-clash-bot/tests/fixtures').rglob('*.png'))
seen=set();matches=[]
for p in paths:
 data=p.read_bytes();sha=hashlib.sha256(data).hexdigest()
 if sha in seen:continue
 seen.add(sha);im=cv2.imread(str(p))
 if im is None or im.shape!=(633,419,3):continue
 roi=im[175:480,43:377];sc=np.minimum(cv2.matchTemplate(roi,t,cv2.TM_CCOEFF_NORMED),cv2.matchTemplate(cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY),gray,cv2.TM_CCOEFF_NORMED));_,score,_,(x,y)=cv2.minMaxLoc(sc)
 if score>=.55:matches.append({'path':str(p),'sha256':sha,'score':score,'sprite_bbox':[x+43,y+175,x2-x1,y2-y1],'source':sha==source_sha})
matches.sort(key=lambda r:r['score'],reverse=True)
(OUT/'template-matches.json').write_text(json.dumps({'crop':crop,'unique_frames':len(seen),'matches':matches},indent=2),encoding='utf8')
print('scanned',len(seen),'matches',len(matches),'top',matches[:8],flush=True)
tiles=[]
for i,m in enumerate(matches[:36]):
 im=cv2.imread(m['path']);x,y,w,h=m['sprite_bbox'];xx1,yy1=max(0,x-30),max(0,y-30);xx2,yy2=min(419,x+65),min(633,y+90)
 crop=cv2.resize(im[yy1:yy2,xx1:xx2],(190,240),interpolation=cv2.INTER_NEAREST);tile=np.zeros((265,190,3),np.uint8);tile[25:]=crop
 cv2.putText(tile,f"{i} {m['score']:.3f} {x},{y}",(3,17),0,.44,(255,255,255),1);tiles.append(tile)
if tiles:
 while len(tiles)%6:tiles.append(np.zeros_like(tiles[0]))
 cv2.imwrite(str(OUT/'template-top-matches.png'),np.vstack([np.hstack(tiles[i:i+6]) for i in range(0,len(tiles),6)]))
