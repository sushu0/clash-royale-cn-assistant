from pathlib import Path
import cv2,json,numpy as np,sys
ROOT=Path(r'D:\codex\CodexWork\clash');BASE=ROOT/'work'/'batch5'/'20260926-170957-candidate2';OUT=BASE/'vision_audit';rows={r['i']:r for r in json.loads((OUT/'map.json').read_text(encoding='utf8'))};f=cv2.imread(rows[65]['file'])
specs=[('g16_top',(150,307,162,319)),('g16_left',(116,333,128,345)),('g16_right',(184,331,196,343)),('g14_blob',(262,361,274,373)),('g14_top',(283,350,295,362)),('own_tower15',(277,383,291,398)),('own_blue15',(271,305,284,317)),('unverified13',(326,360,340,373))]
s=np.full((2*175,4*155,3),245,np.uint8)
for i,(name,(x1,y1,x2,y2))in enumerate(specs):
    p=f[y1:y2,x1:x2];cv2.imwrite(str(OUT/(name+'.png')),p);q=cv2.resize(p,(140,140),interpolation=cv2.INTER_NEAREST);x=i%4*155;y=i//4*175;s[y:y+140,x:x+140]=q;cv2.putText(s,name,(x,y+161),cv2.FONT_HERSHEY_SIMPLEX,.4,(0,0,0),1)
cv2.imwrite(str(OUT/'gold-label-direct.jpg'),s)
