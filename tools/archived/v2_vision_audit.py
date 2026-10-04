from pathlib import Path
import json, sys
import cv2
import numpy as np

ROOT=Path(r'D:\codex\CodexWork\clash')
sys.path.insert(0,str(ROOT/'py-clash-bot'))
from pyclashbot.detection.cn_battle_cues import read_cn_battle_cues, _enemy_tag_mask

OUT=ROOT/'work'/'v2-vision-audit'
OUT.mkdir(exist_ok=True)
files=sorted((ROOT/'work'/'hog-validation'/'20260925-181459').glob('observe-*.png'))
records=[]
def proposed_tags(frame):
    mask,hsv=_enemy_tag_mask(frame)
    repaired=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((3,1),np.uint8))
    new=[]
    for m in (mask,repaired):
        for x,y,w,h,a in cv2.connectedComponentsWithStats(m)[2][1:]:
            small=7<=w<=13 and 7<=h<=8 and y<=300
            wide=14<=w<=44 and 9<=h<=13
            if not (small or wide): continue
            if wide:
                # A long thin health bar touching the plaque to its right.
                extension=m[y:y+h,x+11:x+w]>0
                row_counts=np.count_nonzero(extension,axis=1)
                strong=row_counts>=max(2,(w-11)*.55)
                if not (2<=sum(strong)<=7): continue
            label_w=min(11,w)
            patch=hsv[y:y+h,x:x+label_w]
            white=(patch[:,:,1]<=90)&(patch[:,:,2]>=190)
            density=float(np.mean(m[y:y+h,x:x+label_w]>0))
            if not .2<=density<=.85 or not .18<=float(np.mean(white))<=.65: continue
            marker=(int(x+5),int(y+h//2+16))
            if any(abs(marker[0]-cx)<=7 and abs(marker[1]-cy)<=7 for cx,cy in new):continue
            new.append(marker)
    return new
for i,p in enumerate(files):
    frame=cv2.imread(str(p)); cues=read_cn_battle_cues(frame)
    new=proposed_tags(frame)
    records.append({'i':i,'file':str(p),'cues':cues,'new':new})
for page in range((len(files)+15)//16):
    sheet=np.full((4*344,4*220,3),245,np.uint8)
    for cell,i in enumerate(range(page*16,min(len(files),(page+1)*16))):
        frame=cv2.imread(str(files[i]))
        for x,y in records[i]['cues']['enemies']:
            cv2.circle(frame,(x,y-16),9,(0,255,0),1)
        for x,y in records[i]['new']:
            cv2.circle(frame,(x,y-16),11,(0,0,255),1)
        tile=cv2.resize(frame,(210,317))
        x=(cell%4)*220; y=(cell//4)*344
        sheet[y:y+317,x:x+210]=tile
        text=f"{i} E={records[i]['cues']['elixir']} n={len(records[i]['cues']['enemies'])}+{len(records[i]['new'])}"
        cv2.putText(sheet,text,(x,y+331),cv2.FONT_HERSHEY_SIMPLEX,.43,(0,0,0),1)
    cv2.imwrite(str(OUT/f'frames-{page}.jpg'),sheet)
sheet=np.full((int(np.ceil(len(files)/8))*102,8*115,3),245,np.uint8)
for i,p in enumerate(files):
    frame=cv2.imread(str(p)); tile=frame[427:507,309:400]
    x=(i%8)*115; y=(i//8)*102
    sheet[y:y+80,x:x+91]=tile
    cv2.putText(sheet,str(i),(x,y+96),cv2.FONT_HERSHEY_SIMPLEX,.4,(0,0,0),1)
cv2.imwrite(str(OUT/'skill-crops.jpg'),sheet)
(OUT/'frames.json').write_text(json.dumps(records,indent=2),encoding='utf8')
print(json.dumps({'frames':len(records),'elixir_unknown':sum(r['cues']['elixir'] is None for r in records),'empty_enemy_frames':sum(not r['cues']['enemies'] for r in records)},indent=2))
print(json.dumps({'new_tags':sum(len(r['new']) for r in records),'new_frames':sum(bool(r['new']) for r in records)},indent=2))
ready_labels={1,5,9,11,14,15,25,41,43,46,52,55,56,59,60,69}
source=cv2.imread(str(files[1]))
template=source[450:504,325:381]
gray_template=cv2.cvtColor(template,cv2.COLOR_BGR2GRAY)
cv2.imwrite(str(OUT/'skill-ready-source.png'),template)
gray_source=cv2.imread(str(files[36]))
cv2.imwrite(str(OUT/'skill-grey-source.png'),gray_source[450:504,325:381])
skills=[]
for i,p in enumerate(files):
    frame=cv2.imread(str(p)); roi=frame[425:508,310:396]
    corr=cv2.matchTemplate(cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY),gray_template,cv2.TM_CCOEFF_NORMED)
    _,score,_,(lx,ly)=cv2.minMaxLoc(corr)
    # Color guard at the matched icon's small top-left cost badge.
    cost=roi[ly:ly+25,lx:lx+25]
    h,s,v=cv2.split(cv2.cvtColor(cost,cv2.COLOR_BGR2HSV))
    purple=int(np.count_nonzero((h>=130)&(h<=175)&(s>=110)&(v>=125)))
    predicted=score>=.8 and purple>=25
    fixed=frame[450:504,325:382]
    h,s,v=cv2.split(cv2.cvtColor(fixed,cv2.COLOR_BGR2HSV))
    mag=(h[:25,:25]>=130)&(h[:25,:25]<=175)&(s[:25,:25]>=110)&(v[:25,:25]>=125)
    white=(s[9:53,6:56]<=95)&(v[9:53,6:56]>=205)
    cyan=(h[9:53,6:56]>=85)&(h[9:53,6:56]<=115)&(s[9:53,6:56]>=80)&(v[9:53,6:56]>=150)
    counts=[int(mag.sum()),int(white.sum()),int(cyan.sum())]
    skills.append({'i':i,'file':str(p),'visual_ready':i in ready_labels,'score':score,'purple_cost_pixels':purple,'predicted_ready':predicted,'match_xy':[lx+310,ly+425],'counts':counts})
(OUT/'skill.json').write_text(json.dumps(skills,indent=2),encoding='utf8')
print(json.dumps({'skill_ready_scores':[(s['i'],round(s['score'],3),s['purple_cost_pixels']) for s in skills if s['visual_ready']],'skill_false':[(s['i'],round(s['score'],3),s['purple_cost_pixels']) for s in skills if s['visual_ready']!=s['predicted_ready']],'grey_sample':skills[36]},indent=2))
print('feature_counts',[(s['i'],s['visual_ready'],s['counts'])for s in skills])
