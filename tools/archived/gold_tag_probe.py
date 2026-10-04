from pathlib import Path
import cv2,json,numpy as np
ROOT=Path(r'D:\codex\CodexWork\clash');BASE=ROOT/'work'/'batch5'/'20260926-170957-candidate2';OUT=BASE/'vision_audit';rows={r['i']:r for r in json.loads((OUT/'map.json').read_text(encoding='utf8'))};p=Path(rows[65]['file']);f=cv2.imread(str(p));hsv=cv2.cvtColor(f,cv2.COLOR_BGR2HSV)
gold=((hsv[:,:,0]>=15)&(hsv[:,:,0]<=40)&(hsv[:,:,1]>=130)&(hsv[:,:,2]>=140)).astype(np.uint8)*255;gold[:230]=0;gold[480:]=0
patches=[]
for x,y,w,h,a in cv2.connectedComponentsWithStats(gold)[2][1:]:
    if 5<=w<=16 and 7<=h<=17:
        patches.append((int(x),int(y),int(w),int(h),int(a)))
s=np.full((int(np.ceil(len(patches)/8))*100,1000,3),245,np.uint8)
for i,(x,y,w,h,a)in enumerate(patches):
    p=f[max(0,y-2):y+h+3,max(0,x-2):x+w+3];p=cv2.resize(p,(85,75),interpolation=cv2.INTER_NEAREST);xx=i%8*125;yy=i//8*100;s[yy:yy+75,xx:xx+85]=p;cv2.putText(s,f'{i}:{x},{y},{w},{h}',(xx,yy+91),cv2.FONT_HERSHEY_SIMPLEX,.29,(0,0,0),1)
cv2.imwrite(str(OUT/'gold-tag-candidates.jpg'),s);(OUT/'gold-tag-candidates.json').write_text(json.dumps(patches,indent=2));print(patches)
