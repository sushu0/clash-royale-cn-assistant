from pathlib import Path
import json,cv2,numpy as np
ROOT=Path(r'D:\codex\CodexWork\clash');BASE=ROOT/'work'/'batch5'/'20260926-161656-candidate';OUT=BASE/'vision_audit';rows={r['i']:r for r in json.loads((OUT/'map.json').read_text(encoding='utf8'))};ids=[62,63,64,77,78,80,89,90,91]
t=cv2.imread(str(ROOT/'py-clash-bot'/'pyclashbot'/'detection'/'reference_images'/'cn_threats'/'air_balloon_envelope.png'))
def score(f,t):
    roi=f[185:270,43:377];c=cv2.matchTemplate(roi,t,cv2.TM_CCOEFF_NORMED);g=cv2.matchTemplate(cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY),cv2.cvtColor(t,cv2.COLOR_BGR2GRAY),cv2.TM_CCOEFF_NORMED);_,v,_,(x,y)=cv2.minMaxLoc(np.minimum(c,g));return float(v),(x+43,y+185)
sources=[]
for i in ids:
    f=cv2.imread(rows[i]['file']);value,(x,y)=score(f,t);crop=f[y:y+38,x:x+42]
    if i in [63,90]:
        cv2.imwrite(str(OUT/f'early-balloon-pose-{i}.png'),crop);sources.append((i,crop,(x,y)))
    print(i,round(value,4),(x,y))
for i,t,(x,y) in sources:
    print('source',i,[(j,round(score(cv2.imread(rows[j]['file']),t)[0],4))for j in ids])
