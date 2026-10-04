from pathlib import Path
import json,cv2,numpy as np
ROOT=Path(r'D:\codex\CodexWork\clash');OUT=ROOT/'work'/'v3-threats';rows=json.loads((OUT/'prototype-hits.json').read_text())
for kind in ('air','swarm'):
    hits=[(row['file'],hit)for row in rows for hit in row['hits']if hit['kind']==kind]
    print(kind,len(hits))
    if not hits:continue
    s=np.full((int(np.ceil(len(hits)/8))*112,1000,3),245,np.uint8)
    for i,(file,hit)in enumerate(hits):
        f=cv2.imread(file);x,y,w,h=hit['bbox'];p=f[max(0,y-15):y+h+20,max(0,x-10):x+w+10];p=cv2.resize(p,(100,90));xx=i%8*125;yy=i//8*112;s[yy:yy+90,xx:xx+100]=p
        cv2.putText(s,f'{i}:{hit["confidence"]:.3f}',(xx,yy+108),cv2.FONT_HERSHEY_SIMPLEX,.38,(0,0,0),1)
    cv2.imwrite(str(OUT/(kind+'-all.jpg')),s)
    (OUT/(kind+'-all.json')).write_text(json.dumps(hits,indent=2),encoding='utf8')
f=cv2.imread(str(ROOT/'work'/'hog-validation'/'20260926-005724'/'observe-02-010104.png'))
cv2.imwrite(str(OUT/'goblin-detail.png'),cv2.resize(f[285:350,90:150],None,fx=5,fy=5,interpolation=cv2.INTER_NEAREST))
