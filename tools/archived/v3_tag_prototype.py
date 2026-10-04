from pathlib import Path
import sys,cv2,numpy as np,json
ROOT=Path(r'D:\codex\CodexWork\clash');sys.path.insert(0,str(ROOT/'py-clash-bot'))
from pyclashbot.detection.cn_battle_cues import _enemy_tag_mask,read_cn_battle_cues
SOURCE=ROOT/'work'/'hog-validation'/'20260926-005724'
TEMPLATE_SPECS=(
    ('level13','observe-01-005901.png',(293,242,302,252)),
    ('level14','observe-04-010752.png',(215,395,224,405)),
    ('level15','observe-04-010752.png',(275,370,284,380)),
    ('level15_shield','observe-05-010919.png',(118,315,127,325)),
)
templates=[]
for name,file,(x1,y1,x2,y2)in TEMPLATE_SPECS:
    p=cv2.imread(str(SOURCE/file))[y1:y2,x1:x2]
    templates.append(cv2.cvtColor(cv2.resize(p,(12,12)),cv2.COLOR_BGR2GRAY))

def local_tags(frame):
    mask,hsv=_enemy_tag_mask(frame); binary=(mask>0).astype(np.float32)
    white=((hsv[:,:,1]<=90)&(hsv[:,:,2]>=190)).astype(np.float32)
    candidates=[]
    for w,h in ((9,10),(10,10),(9,9),(10,11),(11,11)):
        ring=np.zeros((h,w),np.float32);ring[0,:]=1;ring[-1,:]=1;ring[:,0]=1;ring[:,-1]=1
        scores=cv2.matchTemplate(binary,ring,cv2.TM_CCORR)
        yy,xx=np.where(scores>=22)
        for y,x in zip(yy,xx):
            if not 230<=y<470 or not 43<=x<367:continue
            p=binary[y:y+h,x:x+w]
            if p[0].sum()<6 or p[-1].sum()<6 or p[:,0].sum()<6 or p[:,-1].sum()<4:continue
            wf=white[y:y+h,x:x+w].mean()
            if not .20<=wf<=.65 or not .20<=p.mean()<=.85:continue
            marker=(int(x+w//2),int(y+h//2+16))
            if any(abs(marker[0]-a)<=7 and abs(marker[1]-b)<=7 for (a,b),_,_ in candidates):continue
            gray=cv2.cvtColor(cv2.resize(frame[y:y+h,x:x+w],(12,12)),cv2.COLOR_BGR2GRAY)
            glyph=max(float(cv2.matchTemplate(gray,t,cv2.TM_CCOEFF_NORMED)[0,0])for t in templates)
            candidates.append((marker,glyph,(int(x),int(y),w,h)))
    return candidates

out=ROOT/'work'/'v3-vision-audit';rows=json.loads((out/'frames.json').read_text(encoding='utf8'))
allnew=[]
for r in rows:
    f=cv2.imread(r['file']);new=[(p,score,box) for p,score,box in local_tags(f) if not any(abs(p[0]-a)<=7 and abs(p[1]-b)<=7 for a,b in r['cues']['enemies'])]
    r['new']=new
    for pt,score,box in new:allnew.append((r['i'],r['file'],pt,score,box))
sheet=np.full((int(np.ceil(len(allnew)/8))*110,8*125,3),245,np.uint8)
for j,(i,name,(x,y),score,box)in enumerate(allnew):
    f=cv2.imread(name);p=f[max(0,y-41):y+9,max(0,x-25):x+25]
    p=cv2.resize(p,(100,100),interpolation=cv2.INTER_NEAREST);xx=j%8*125;yy=j//8*110
    sheet[yy:yy+100,xx:xx+100]=p;cv2.putText(sheet,f'{i}:{score:.2f}',(xx,yy+108),cv2.FONT_HERSHEY_SIMPLEX,.3,(0,0,0),1)
cv2.imwrite(str(out/'local-tag-new.jpg'),sheet)
(out/'local-tag-prototype.json').write_text(json.dumps(rows,indent=2),encoding='utf8')
print('new count',len(allnew));print(allnew)
