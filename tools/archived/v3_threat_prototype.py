from pathlib import Path
import sys,cv2,json,hashlib,time,numpy as np
ROOT=Path(r'D:\codex\CodexWork\clash');sys.path.insert(0,str(ROOT/'py-clash-bot'))
from pyclashbot.detection.cn_battle_cues import read_cn_battle_cues
OUT=ROOT/'work'/'v3-threats';SOURCE=ROOT/'work'/'hog-validation'
specs=[
 {'id':'air_barrel_red','kind':'air','file':'20260926-005724/observe-01-005913.png','box':(310,291,342,318),'anchor':(323,297)},
 {'id':'swarm_goblin_green','kind':'swarm','file':'20260926-005724/observe-02-010104.png','box':(99,317,114,329),'anchor':(109,325)},
 {'id':'rush_hog_rider','kind':'rush','file':'20260926-115400/observe-02-120002.png','box':(87,339,122,369),'anchor':(97,347)},
]
for spec in specs:
    source=SOURCE/spec['file'];frame=cv2.imread(str(source));x1,y1,x2,y2=spec['box'];tpl=frame[y1:y2,x1:x2];spec['template']=tpl;spec['gray']=cv2.cvtColor(tpl,cv2.COLOR_BGR2GRAY)
    cv2.imwrite(str(OUT/(spec['id']+'.png')),tpl)

def identify(frame,enemies):
    result=[]
    hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    for ex,ey in enemies:
        tag=hsv[max(0,ey-23):ey-8,max(0,ex-7):ex+8];red=(((tag[:,:,0]<=9)|(tag[:,:,0]>=166))&(tag[:,:,1]>=125)&(tag[:,:,2]>=75)).sum()
        if red<20:continue
        choices=[]
        for spec in specs:
            tx,ty,tx2,ty2=spec['box'];a,b=spec['anchor'];dx,dy=tx-a,ty-b;w,h=tx2-tx,ty2-ty
            x1=max(0,ex+dx-8);y1=max(0,ey+dy-8);x2=min(419,ex+dx+w+8);y2=min(510,ey+dy+h+8)
            roi=frame[y1:y2,x1:x2]
            if roi.shape[0]<h or roi.shape[1]<w:continue
            col=cv2.matchTemplate(roi,spec['template'],cv2.TM_CCOEFF_NORMED)
            gray=cv2.matchTemplate(cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY),spec['gray'],cv2.TM_CCOEFF_NORMED)
            score=np.minimum(col,gray);_,score,_,(mx,my)=cv2.minMaxLoc(score)
            choices.append({'kind':spec['kind'],'template_id':spec['id'],'confidence':score,'x':ex,'y':ey,'bbox':[mx+x1,my+y1,w,h]})
        if choices:
            top=max(choices,key=lambda x:x['confidence'])
            if top['confidence']>=.70:result.append(top)
    return result

files=sorted(SOURCE.glob('*/observe-*.png'))+sorted((OUT/'source').glob('recent-play-before-*.png'))
rows=[];t=time.perf_counter()
for p in files:
    f=cv2.imread(str(p));e=read_cn_battle_cues(f)['enemies'];hits=identify(f,e)
    if hits:rows.append({'file':str(p),'hits':hits})
(OUT/'prototype-hits.json').write_text(json.dumps(rows,indent=2),encoding='utf8')
print('frames',len(files),'seconds',time.perf_counter()-t)
for kind in ('air','rush','swarm'):
    high=[(r['file'],h)for r in rows for h in r['hits']if h['kind']==kind and h['confidence']>=.88]
    print(kind,len(high),high)
    if not high:continue
    sheet=np.full((int(np.ceil(len(high)/8))*110,1000,3),245,np.uint8)
    for i,(file,hit)in enumerate(high):
        f=cv2.imread(file);x,y,w,h=hit['bbox'];p=f[max(0,y-8):min(633,y+h+8),max(0,x-8):min(419,x+w+8)];p=cv2.resize(p,(95,90));xx=i%8*125;yy=i//8*110;sheet[yy:yy+90,xx:xx+95]=p;cv2.putText(sheet,f'{i}:{hit["confidence"]:.2f}',(xx,yy+105),cv2.FONT_HERSHEY_SIMPLEX,.38,(0,0,0),1)
    cv2.imwrite(str(OUT/f'{kind}-hits.jpg'),sheet)
