from pathlib import Path
import json, sys
import cv2
import numpy as np

ROOT=Path(r'D:\codex\CodexWork\clash')
sys.path.insert(0,str(ROOT/'py-clash-bot'))
from pyclashbot.detection.cn_battle_cues import read_cn_battle_cues
from pyclashbot.bot.coords import CN_HOG_ELIXIR_X_COORDS, CN_HOG_ELIXIR_Y

OUT=ROOT/'work'/'v2-vision-audit'
baseline=json.loads((OUT/'baseline-all.json').read_text())
records=[]
for filename, old in baseline.items():
    frame=cv2.imread(str(ROOT/filename))
    new=read_cn_battle_cues(frame)
    missing=[pt for pt in old['enemies'] if not any(abs(pt[0]-x)<=7 and abs(pt[1]-y)<=7 for x,y in new['enemies'])]
    added=[pt for pt in new['enemies'] if not any(abs(pt[0]-x)<=7 and abs(pt[1]-y)<=7 for x,y in old['enemies'])]
    records.append({'file':filename,'old':old,'new':new,'added':added,'missing':missing})
latest=[r for r in records if '20260925-181459' in r['file'] and 'observe-' in r['file']]
latest.sort(key=lambda r:r['file'])
ready_labels={1,5,9,11,14,15,25,41,43,46,52,55,56,59,60,69}
skill_mismatches=[{'i':i,'file':r['file']} for i,r in enumerate(latest) if r['new']['elite_ability_ready']!=(i in ready_labels)]
positives=[r for r in records if r['new']['elite_ability_ready']]
sheet=np.full((int(np.ceil(len(positives)/10))*90,10*100,3),245,np.uint8)
for i,r in enumerate(positives):
    f=cv2.imread(str(ROOT/r['file']))
    x=(i%10)*100;y=(i//10)*90
    sheet[y:y+65,x:x+80]=f[440:505,315:395]
    cv2.putText(sheet,str(i),(x,y+83),cv2.FONT_HERSHEY_SIMPLEX,.4,(0,0,0),1)
cv2.imwrite(str(OUT/'all-ready.jpg'),sheet)
summary={
    'total_frames':len(records),
    'unchanged_known_elixir':all(r['old']['elixir'] is None or r['old']['elixir']==r['new']['elixir'] for r in records),
    'recovered_elixir_frames':[{'file':r['file'],'new':r['new']['elixir']}for r in records if r['old']['elixir'] is None and r['new']['elixir'] is not None],
    'unchanged_towers':all(r['old']['enemy_towers']==r['new']['enemy_towers'] for r in records),
    'old_enemy_markers_missing':sum(len(r['missing'])for r in records),
    'new_enemy_markers':sum(len(r['added'])for r in records),
    'latest_observe_frames':len(latest),
    'latest_added_markers':sum(len(r['added'])for r in latest),
    'latest_added_marker_frames':sum(bool(r['added'])for r in latest),
    'latest_elixir_unknown_before':sum(r['old']['elixir'] is None for r in latest),
    'latest_elixir_unknown_after':sum(r['new']['elixir'] is None for r in latest),
    'latest_skill_ready_visual_labels':len(ready_labels),
    'latest_skill_nonready_visual_labels':len(latest)-len(ready_labels),
    'latest_skill_mismatches':skill_mismatches,
    'all_ready_frames':len(positives),
    'limitations':['Only fixed 419x633 battle screenshots. Invoke after battle-state verification.','Enemy markers are pressure observations, not units or air/ground classification.','Small labels outside the bridge remain excluded because tower trim creates false positives.','Ready button is a visual state; ability effect and cooldown duration not inferred.'],
}
def elixir_frame(prefix):
    f=np.zeros((633,419,3),np.uint8)
    f[CN_HOG_ELIXIR_Y,CN_HOG_ELIXIR_X_COORDS]=(117,49,4)
    f[CN_HOG_ELIXIR_Y,CN_HOG_ELIXIR_X_COORDS[:prefix]]=(244,137,240)
    return f

safety_cases=[]
def check(name,actual,expected):
    assert actual==expected,(name,actual,expected)
    safety_cases.append(name)

for bad in (None,np.zeros((633,419),np.uint8),np.zeros((633,419,3),np.float32)):
    check('invalid_frame_rejected',read_cn_battle_cues(bad)['elite_ability_ready'],False)
f=elixir_frame(3)
f[CN_HOG_ELIXIR_Y,CN_HOG_ELIXIR_X_COORDS[3]]=(197,111,91)
check('one_observed_transition_returns_lower_bound',read_cn_battle_cues(f)['elixir'],3)
f[CN_HOG_ELIXIR_Y,CN_HOG_ELIXIR_X_COORDS[4]]=(197,111,91)
check('two_unknown_transitions_rejected',read_cn_battle_cues(f)['elixir'],None)
f=elixir_frame(3)
f[CN_HOG_ELIXIR_Y,CN_HOG_ELIXIR_X_COORDS[3]]=(0,0,0)
check('arbitrary_bad_boundary_rejected',read_cn_battle_cues(f)['elixir'],None)
f=elixir_frame(3)
f[CN_HOG_ELIXIR_Y,CN_HOG_ELIXIR_X_COORDS[5]]=(244,137,240)
check('filled_island_rejected',read_cn_battle_cues(f)['elixir'],None)
for color in ((255,255,255),(0,0,0),(255,80,230)):
    f=np.full((633,419,3),color,np.uint8)
    check('flat_color_is_not_ability',read_cn_battle_cues(f)['elite_ability_ready'],False)
summary['safety_checks_passed']=safety_cases
(OUT/'regression.json').write_text(json.dumps({'summary':summary,'records':records},indent=2),encoding='utf8')
(ROOT/'work'/'v2-vision-audit.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
print(json.dumps(summary,indent=2))
