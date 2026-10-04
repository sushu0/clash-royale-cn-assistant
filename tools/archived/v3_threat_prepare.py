from pathlib import Path
import cv2,hashlib,json,numpy as np
ROOT=Path(r'D:\codex\CodexWork\clash');SRC=ROOT/'work'/'hog-validation'/'20260926-115400';OUT=ROOT/'work'/'v3-threats';OUT.mkdir(exist_ok=True)
snap=OUT/'source';snap.mkdir(exist_ok=True)
records=[]
for p in sorted(SRC.glob('*.png')):
    if not (p.name.startswith('observe-')or p.name.startswith('recent-play-before-')):continue
    b=p.read_bytes();h=hashlib.sha256(b).hexdigest();image=cv2.imdecode(np.frombuffer(b,np.uint8),cv2.IMREAD_COLOR)
    if image is None:continue
    if hashlib.sha256(p.read_bytes()).hexdigest()!=h:continue
    target=snap/(p.stem+'-'+h[:12]+'.png');target.write_bytes(b)
    records.append({'original':str(p),'snapshot':str(target),'sha256':h})
(OUT/'source-manifest.json').write_text(json.dumps(records,indent=2),encoding='utf8')
obs=[r for r in records if Path(r['original']).name.startswith('observe-')]
for page in range((len(obs)+15)//16):
    sheet=np.full((4*339,4*215,3),245,np.uint8)
    for k,i in enumerate(range(page*16,min(len(obs),(page+1)*16))):
        f=cv2.imread(obs[i]['snapshot']);tile=cv2.resize(f,(210,317));x=k%4*215;y=k//4*339;sheet[y:y+317,x:x+210]=tile
        cv2.putText(sheet,f'{i} '+Path(obs[i]['original']).stem[-6:],(x,y+332),cv2.FONT_HERSHEY_SIMPLEX,.4,(0,0,0),1)
    cv2.imwrite(str(OUT/f'obs-{page}.jpg'),sheet)
(OUT/'observe-map.json').write_text(json.dumps(obs,indent=2),encoding='utf8')
print('copied',len(records),'observe',len(obs))
