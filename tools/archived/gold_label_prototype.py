from pathlib import Path
import cv2,json,numpy as np,time
ROOT=Path(r'D:\codex\CodexWork\clash');BASE=ROOT/'work'/'batch5'/'20260926-170957-candidate2';OUT=BASE/'vision_audit';rows={r['i']:r for r in json.loads((OUT/'map.json').read_text(encoding='utf8'))}
specs=[('gold14',61,(275,271,284,281)),('gold16',65,(117,334,126,344))];templates=[]
for name,i,(x1,y1,x2,y2)in specs:
    f=cv2.imread(rows[i]['file']);t=f[y1:y2,x1:x2];cv2.imwrite(str(OUT/(name+'-template.png')),t);templates.append((name,t,cv2.cvtColor(t,cv2.COLOR_BGR2GRAY)))
results=[]
for r in rows.values():
    if r['event']not in('play','observe'):continue
    f=cv2.imread(r['file']);roi=f[230:480,43:377];hsv=cv2.cvtColor(f,cv2.COLOR_BGR2HSV);found=[]
    for name,t,g in templates:
        scores=np.minimum(cv2.matchTemplate(roi,t,cv2.TM_CCOEFF_NORMED),cv2.matchTemplate(cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY),g,cv2.TM_CCOEFF_NORMED));h,w=t.shape[:2]
        for _ in range(20):
            _,v,_,(x,y)=cv2.minMaxLoc(scores)
            if v<.90:break
            scores[max(0,y-5):y+6,max(0,x-5):x+6]=-1;x+=43;y+=230;p=hsv[y:y+h,x:x+w]
            gold=(p[:,:,0]>=10)&(p[:,:,0]<=40)&(p[:,:,1]>=100)&(p[:,:,2]>=140)
            red=(((p[:,:,0]<=9)|(p[:,:,0]>=166))&(p[:,:,1]>=120)&(p[:,:,2]>=60))
            if gold.mean()<.20 or red.mean()<.15:continue
            point=(x+w//2,y+h//2+16)
            if any(abs(point[0]-z['point'][0])<=7 and abs(point[1]-z['point'][1])<=7 for z in found):continue
            found.append({'template':name,'point':point,'box':[x,y,w,h],'score':v,'gold_fraction':float(gold.mean()),'red_fraction':float(red.mean())})
    if found:results.append({'i':r['i'],'battle':r['battle'],'file':r['file'],'hits':found})
(OUT/'gold-prototype.json').write_text(json.dumps(results,indent=2),encoding='utf8')
flat=[(r['i'],r['file'],h)for r in results for h in r['hits']];s=np.full((int(np.ceil(len(flat)/10))*90,1000,3),245,np.uint8)
for i,(row,file,h)in enumerate(flat):
    f=cv2.imread(file);x,y,w,hh=h['box'];p=cv2.resize(f[y-3:y+hh+12,x-5:x+w+12],(80,70),interpolation=cv2.INTER_NEAREST);xx=i%10*100;yy=i//10*90;s[yy:yy+70,xx:xx+80]=p;cv2.putText(s,f'{i}:{row}',(xx,yy+85),cv2.FONT_HERSHEY_SIMPLEX,.35,(0,0,0),1)
if flat:cv2.imwrite(str(OUT/'gold-prototype-crops.jpg'),s)
print(json.dumps({'frames':len(results),'markers':len(flat),'by_event':[(r['i'],len(r['hits']))for r in results]},indent=2))
