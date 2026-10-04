from pathlib import Path
import cv2,json,numpy as np
ROOT=Path(r'D:\codex\CodexWork\clash');OUT=Path(__file__).parent;RUN=ROOT/'work/567-validation/20260928-155830'
templates=[]
for name,file,crop in [('front_metal','play-10-bomber-before.png',(75,248,97,261)),('diagonal_metal_green','observe-01-160026.png',(70,241,98,269))]:
 src=cv2.imread(str(RUN/file));x1,y1,x2,y2=crop;t=src[y1:y2,x1:x2];templates.append((name,t,cv2.cvtColor(t,cv2.COLOR_BGR2GRAY)));cv2.imwrite(str(OUT/(name+'.png')),t)
results=[]
paths=list(OUT.glob('[0-9a-f]'*64+'.png'))+list((ROOT/'work/567-optimize/vision').glob('[0-9a-f]'*64+'.png'))+list((ROOT/'py-clash-bot/tests/fixtures').rglob('*.png'))
seen=set()
for p in paths:
 if p.name in seen:continue
 seen.add(p.name);im=cv2.imread(str(p))
 if im is None or im.shape!=(633,419,3):continue
 roi=im[175:480,43:377];gray=cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY)
 for name,t,tgray in templates:
  sc=np.minimum(cv2.matchTemplate(roi,t,cv2.TM_CCOEFF_NORMED),cv2.matchTemplate(gray,tgray,cv2.TM_CCOEFF_NORMED));_,score,_,(x,y)=cv2.minMaxLoc(sc)
  if score>=.62:results.append({'template':name,'score':score,'path':str(p),'bbox':[x+43,y+175,t.shape[1],t.shape[0]]})
results.sort(key=lambda r:r['score'],reverse=True);(OUT/'helmet-matches.json').write_text(json.dumps(results,indent=2),encoding='utf8');print(len(seen),len(results),results[:8])
tiles=[]
for i,r in enumerate(results[:48]):
 im=cv2.imread(r['path']);x,y,w,h=r['bbox'];crop=im[max(0,y-30):min(510,y+75),max(0,x-25):min(419,x+65)];crop=cv2.resize(crop,(180,210),interpolation=cv2.INTER_NEAREST)
 tile=np.zeros((235,180,3),np.uint8);tile[25:]=crop;cv2.putText(tile,f'{i} {r["score"]:.3f} {x},{y}',(2,17),0,.42,(255,255,255),1);tiles.append(tile)
if tiles:
 while len(tiles)%6:tiles.append(np.zeros_like(tiles[0]))
 cv2.imwrite(str(OUT/'helmet-matches.png'),np.vstack([np.hstack(tiles[i:i+6]) for i in range(0,len(tiles),6)]))
