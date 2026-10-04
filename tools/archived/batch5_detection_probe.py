from pathlib import Path
import sys,json,cv2,numpy as np
ROOT=Path(r'D:\codex\CodexWork\clash');sys.path.insert(0,str(ROOT/'py-clash-bot'))
from pyclashbot.detection.cn_battle_cues import _enemy_tag_mask,_level_glyph_templates
BASE=ROOT/'work'/'batch5'/'20260926-1535-baseline';OUT=BASE/'vision_audit';records=json.loads((OUT/'map.json').read_text(encoding='utf8'))
source=next(r for r in records if r['i']==53);f=cv2.imread(source['file']);template=f[305:343,289:331];gray=cv2.cvtColor(template,cv2.COLOR_BGR2GRAY);cv2.imwrite(str(OUT/'air_balloon_envelope-candidate.png'),template)
matches=[]
for row in records:
    f=cv2.imread(row['file']);enemies=row['data'].get('cues',{}).get('enemies',[])
    for ex,ey in enemies:
        x1=max(0,ex-12-8);y1=max(0,ey-12-8);x2=min(419,ex-12+42+8);y2=min(510,ey-12+38+8);p=f[y1:y2,x1:x2]
        if p.shape[0]<38 or p.shape[1]<42:continue
        col=cv2.matchTemplate(p,template,cv2.TM_CCOEFF_NORMED);gry=cv2.matchTemplate(cv2.cvtColor(p,cv2.COLOR_BGR2GRAY),gray,cv2.TM_CCOEFF_NORMED);_,score,_,(mx,my)=cv2.minMaxLoc(np.minimum(col,gry))
        if score>=.65:matches.append({'i':row['i'],'time':row['time'],'battle':row['battle'],'score':score,'point':[ex,ey],'box':[x1+mx,y1+my,42,38],'file':row['file']})
glyphs=_level_glyph_templates();diagnostics=[]
row=next(r for r in records if r['i']==54);f=cv2.imread(row['file']);mask,hsv=_enemy_tag_mask(f)
for mode,m in [('raw',mask),('repaired',cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((3,1),np.uint8)))]:
    for x,y,w,h,area in cv2.connectedComponentsWithStats(m)[2][1:]:
        if 300<x<325 and 352<y<375 and w>=7 and h>=7:
            patch=f[y:y+h,x:x+w];g=cv2.cvtColor(cv2.resize(patch,(12,12)),cv2.COLOR_BGR2GRAY);score=max(float(cv2.matchTemplate(g,t,cv2.TM_CCOEFF_NORMED)[0,0])for t in glyphs);diagnostics.append({'mode':mode,'bbox':[int(x),int(y),int(w),int(h)],'glyph_score':score,'area':int(area)})
            cv2.imwrite(str(OUT/f'own-tower-false-{mode}.png'),cv2.resize(patch,None,fx=10,fy=10,interpolation=cv2.INTER_NEAREST))
(OUT/'detection-probe.json').write_text(json.dumps({'balloon_matches':matches,'own_tower_false':diagnostics},indent=2),encoding='utf8')
print(json.dumps({'matches':[{k:v for k,v in x.items()if k!='file'}for x in matches],'false':diagnostics},indent=2))
