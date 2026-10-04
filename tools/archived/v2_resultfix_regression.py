from pathlib import Path
import cv2, json, sys
import numpy as np

ROOT=Path(r'D:\codex\CodexWork\clash')
sys.path.insert(0,str(ROOT/'py-clash-bot'))
from pyclashbot.bot.cn_1v1_loop import ChineseVision, SEARCH_REGIONS, THRESHOLDS
OUT=ROOT/'work'/'v2-resultfix-audit'
old=json.loads((OUT/'baseline.json').read_text(encoding='utf8'))
v=ChineseVision()
rows=[]
for name,before in old.items():
    f=cv2.imread(name);after=v.outcome(f)
    matches={}
    for key in ('result_loss_yellow','result_loss_yellow_confetti'):
        x1,y1,x2,y2=SEARCH_REGIONS[key]
        _,score,_,loc=cv2.minMaxLoc(cv2.matchTemplate(cv2.cvtColor(f[y1:y2,x1:x2],cv2.COLOR_BGR2GRAY),cv2.cvtColor(v.templates[key],cv2.COLOR_BGR2GRAY),cv2.TM_CCOEFF_NORMED))
        matches[key]=float(score)
    rows.append({'file':name,'before':before,'after':after,'scores':matches})
assert all(r['before']=='未知' or r['before']==r['after'] for r in rows)
assert not any(r['after']=='胜利'and r['before']!='胜利'for r in rows)
required=[('20260925-232740','result-05.png'),('20260925-234557','result-03.png'),('20260925-234557','result-04.png')]
for session,file in required:
    assert next(r['after']for r in rows if session in r['file']and r['file'].endswith(file))=='失败'
# The new patterns must not classify the captured active-battle/lobby frames.
nonresult=[]
extra_results=[]
nonresult_checked=0
for p in sorted((ROOT/'work'/'hog-validation').glob('*/*.png')):
    if p.name.startswith('result-'):continue
    f=cv2.imread(str(p))
    if v.classify(f)[0]=='result':
        extra_results.append(str(p))
        continue
    nonresult_checked+=1
    if any(v.find(f,k)for k in ('result_loss_yellow','result_loss_yellow_confetti')):
        nonresult.append(str(p))
summary={'result_frames':len(rows),'known_wins_preserved':sum(r['before']=='胜利'and r['after']=='胜利'for r in rows),'known_losses_preserved':sum(r['before']=='失败'and r['after']=='失败'for r in rows),'changed':[r for r in rows if r['before']!=r['after']],'new_false_wins':sum(r['before']!='胜利'and r['after']=='胜利'for r in rows),'nonresult_new_template_matches':nonresult,'nonresult_frames_checked':nonresult_checked,'additional_result_screen_files':extra_results,'thresholds':{k:THRESHOLDS[k]for k in ('result_loss','result_loss_alt','result_win','result_loss_yellow','result_loss_yellow_confetti')},'backup':str(ROOT/'work'/'backups'/'hog-v2-resultfix-20260925-235825'),'rollback':'Restore backed-up cn_1v1_loop.py. The two additional PNGs become unused; existing templates were not changed.'}
assert not nonresult,nonresult
(OUT/'regression.json').write_text(json.dumps({'summary':summary,'records':rows},ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(summary,ensure_ascii=True,indent=2))
