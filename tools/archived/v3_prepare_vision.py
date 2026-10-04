from pathlib import Path
import sys,json,cv2,shutil
ROOT=Path(r'D:\codex\CodexWork\clash');sys.path.insert(0,str(ROOT/'py-clash-bot'))
from pyclashbot.detection.cn_battle_cues import read_cn_battle_cues
out=ROOT/'work'/'v3-vision-audit';source=ROOT/'work'/'hog-validation'/'20260926-005724'
frames={str(p):read_cn_battle_cues(cv2.imread(str(p)))for p in (ROOT/'work'/'hog-validation').glob('*/*.png')}
(out/'baseline-all.json').write_text(json.dumps(frames,indent=2),encoding='utf8')
reference=ROOT/'py-clash-bot'/'pyclashbot'/'detection'/'reference_images'/'cn_enemy_tags'
reference.mkdir(exist_ok=True)
specs=(('level13','observe-01-005901.png',(293,242,302,252)),('level14','observe-04-010752.png',(215,395,224,405)),('level15','observe-04-010752.png',(275,370,284,380)),('level15_shield','observe-05-010919.png',(118,315,127,325)))
for name,file,(x1,y1,x2,y2)in specs:
    f=cv2.imread(str(source/file));assert cv2.imwrite(str(reference/(name+'.png')),f[y1:y2,x1:x2])
fixtures=ROOT/'py-clash-bot'/'tests'/'fixtures'/'cn_battle_cues';fixtures.mkdir(exist_ok=True)
for name,file in (('deep_tank_cluster.png','observe-04-010752.png'),('split_swarm.png','observe-05-010919.png'),('balloon_highlight.png','observe-01-005913.png'),('empty_lanes.png','observe-01-005817.png')):
    shutil.copyfile(source/file,fixtures/name)
shutil.copyfile(ROOT/'work'/'hog-validation'/'20260925-181459'/'observe-02-182000.png',fixtures/'own_tower_trim.png')
print('baseline frames',len(frames),'templates',len(specs))
