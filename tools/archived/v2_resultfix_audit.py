from pathlib import Path
import cv2, json, sys
import numpy as np

ROOT=Path(r'D:\codex\CodexWork\clash')
sys.path.insert(0,str(ROOT/'py-clash-bot'))
from pyclashbot.bot.cn_1v1_loop import ChineseVision, TEMPLATES, SEARCH_REGIONS, THRESHOLDS
OUT=ROOT/'work'/'v2-resultfix-audit'
OUT.mkdir(exist_ok=True)
vision=ChineseVision()
files=sorted((ROOT/'work'/'hog-validation').glob('*/result-*.png'))
old={str(p):vision.outcome(cv2.imread(str(p))) for p in files}
(OUT/'baseline.json').write_text(json.dumps(old,indent=2,ensure_ascii=False),encoding='utf8')
source=ROOT/'work'/'hog-validation'/'20260925-234557'/'result-04.png'
frame=cv2.imread(str(source))
crop=frame[59:79,175:239]
cv2.imwrite(str(OUT/'result_loss_yellow.png'),crop)
gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
glow_source=ROOT/'work'/'hog-validation'/'20260925-234557'/'result-03.png'
glow=cv2.imread(str(glow_source))[59:79,175:239]
cv2.imwrite(str(OUT/'result_loss_yellow_glow.png'),glow)
gray_glow=cv2.cvtColor(glow,cv2.COLOR_BGR2GRAY)
report=[]
for p in files:
    f=cv2.imread(str(p))
    roi=f[50:90,160:255]
    _,score,_,loc=cv2.minMaxLoc(cv2.matchTemplate(cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY),gray,cv2.TM_CCOEFF_NORMED))
    _,glow_score,_,glow_loc=cv2.minMaxLoc(cv2.matchTemplate(cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY),gray_glow,cv2.TM_CCOEFF_NORMED))
    report.append({'file':str(p),'before':old[str(p)],'score':score,'glow_score':glow_score,'loc':loc})
(OUT/'candidate-scores.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf8')
print(json.dumps({'result_frames':len(files),'known_wins':sum(v=='胜利'for v in old.values()),'known_losses':sum(v=='失败'for v in old.values()),'unknowns':sum(v=='未知'for v in old.values()),'new_session':[r for r in report if '20260925-234557'in r['file']],'max_known_win_score':max(r['score']for r in report if r['before']=='胜利'),'unknown_candidates':[r for r in report if r['before']=='未知']},indent=2,ensure_ascii=False))
new_unknown=[cv2.imread(str(p))for p in files if old[str(p)]=='未知']
for x1,y1,x2,y2 in [(175,60,239,76),(175,59,230,78),(207,59,239,78),(176,60,217,77),(181,61,235,76)]:
    t=cv2.cvtColor(frame[y1:y2,x1:x2],cv2.COLOR_BGR2GRAY)
    scores=[float(cv2.minMaxLoc(cv2.matchTemplate(cv2.cvtColor(f[50:90,160:255],cv2.COLOR_BGR2GRAY),t,cv2.TM_CCOEFF_NORMED))[1])for f in new_unknown]
    print('crop',(x1,y1,x2,y2),scores)
