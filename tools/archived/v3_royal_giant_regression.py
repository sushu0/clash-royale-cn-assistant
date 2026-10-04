from pathlib import Path
import sys,json,cv2,hashlib,time
ROOT=Path(r'D:\codex\CodexWork\clash');sys.path.insert(0,str(ROOT/'py-clash-bot'))
from pyclashbot.detection.cn_battle_cues import read_cn_battle_cues
OUT=ROOT/'work'/'v3-royal-giant';files=sorted((ROOT/'work'/'hog-validation').glob('*/observe-*.png'))+sorted((ROOT/'work'/'hog-validation').glob('*/play-*.png'))
hits=[];start=time.perf_counter()
for p in files:
    c=read_cn_battle_cues(cv2.imread(str(p)));h=[t for t in c['threats']if t['template_id']=='rush_royal_giant_head']
    if h:hits.append({'file':str(p),'threats':h})
manifest=ROOT/'py-clash-bot'/'pyclashbot'/'detection'/'reference_images'/'cn_threats'/'manifest.json'
summary={'frames':len(files),'seconds':round(time.perf_counter()-start,2),'hits':len(hits),'template_id':'rush_royal_giant_head','threshold':.88,'module_sha256':hashlib.sha256((ROOT/'py-clash-bot'/'pyclashbot'/'detection'/'cn_threats.py').read_bytes()).hexdigest(),'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),'historical_other_session_hits':sum('20260926-122831'not in r['file']for r in hits),'source_frames':['observe-01-122911.png','play-02-musketeer-before.png'],'independent_other_time_frames':['play-02-musketeer-after.png','play-03-fireball-before.png','play-04-log-after.png']}
(OUT/'regression.json').write_text(json.dumps({'summary':summary,'hits':hits},indent=2),encoding='utf8')
print(json.dumps(summary,indent=2))
