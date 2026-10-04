from pathlib import Path
from collections import Counter,defaultdict
from datetime import datetime
import json,sys,cv2
import numpy as np

ROOT=Path(r'D:\codex\CodexWork\clash')
sys.path.insert(0,str(ROOT/'py-clash-bot'))
from pyclashbot.detection.cn_battle_cues import read_cn_battle_cues
from pyclashbot.bot.card_detection import identify_hog_hand_frame

OUT=ROOT/'work'/'v3-vision-audit';OUT.mkdir(exist_ok=True)
files=sorted((ROOT/'work'/'hog-validation'/'20260926-005724').glob('observe-*.png'))
records=[]
for i,p in enumerate(files):
    f=cv2.imread(str(p));c=read_cn_battle_cues(f);h=identify_hog_hand_frame(f)
    records.append({'i':i,'file':str(p),'cues':c,'hand':h})
for page in range((len(files)+15)//16):
    sheet=np.full((4*344,4*220,3),245,np.uint8)
    for cell,i in enumerate(range(page*16,min(len(files),(page+1)*16))):
        f=cv2.imread(str(files[i]));r=records[i]
        for x,y in r['cues']['enemies']:cv2.circle(f,(x,y-16),9,(0,255,0),1)
        tile=cv2.resize(f,(210,317));x=(cell%4)*220;y=(cell//4)*344
        sheet[y:y+317,x:x+210]=tile
        label=f"{i} E={r['cues']['elixir']} n={len(r['cues']['enemies'])}"
        cv2.putText(sheet,label,(x,y+331),cv2.FONT_HERSHEY_SIMPLEX,.43,(0,0,0),1)
    cv2.imwrite(str(OUT/f'frames-{page}.jpg'),sheet)
traces=[]
with (ROOT/'outputs'/'cn-hog-strategy.jsonl').open(encoding='utf8')as inp:
    for line in inp:
        try:r=json.loads(line)
        except json.JSONDecodeError:continue
        if r.get('session')=='20260926-005724':traces.append(r)
plays=[r for r in traces if r.get('event')=='play']
ends=[r for r in traces if r.get('event')=='battle_end']
observe=[r for r in traces if r.get('event')=='observe']
summary={'session':'20260926-005724','last_trace_time':traces[-1]['time'],'screenshot_observe_count':len(files),'max_screenshot_mtime':max(datetime.fromtimestamp(p.stat().st_mtime).isoformat()for p in (ROOT/'work'/'hog-validation'/'20260926-005724').glob('*.png')),'battle_results':dict(Counter(r['result']for r in ends)),'plays':len(plays),'confirmed':sum(r.get('confirmed',False)for r in plays),'confirm_changed_only':sum(r.get('confirmed',False)and r.get('changed_card',False)and r.get('observed_spend',0)<=0 for r in plays),'confirmed_low_spend_same_card':sum(r.get('confirmed',False)and not r.get('changed_card',False)and r.get('observed_spend',0)<=0 for r in plays),'played_variants':dict(Counter(r['decision']['variant']for r in plays)),'defense_points':dict(Counter(str((r['decision']['card'],r['decision']['point']))for r in plays if r['decision']['category']=='defense')),'empty_enemy_observes':sum(not r['cues']['enemies']for r in observe),'total_observes':len(observe)}
(OUT/'frames.json').write_text(json.dumps(records,indent=2,ensure_ascii=False),encoding='utf8')
(OUT/'trace-summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf8')
print(json.dumps(summary,ensure_ascii=True,indent=2))
