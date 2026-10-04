from pathlib import Path
import cv2,json,hashlib,shutil
ROOT=Path(r'D:\codex\CodexWork\clash');REP=ROOT/'py-clash-bot';SRC=ROOT/'work'/'hog-validation'
OUT=ROOT/'work'/'v3-threats';tpl=REP/'pyclashbot'/'detection'/'reference_images'/'cn_threats';tpl.mkdir(exist_ok=True)
source=SRC/'20260926-005724'/'observe-01-005913.png';digest=hashlib.sha256(source.read_bytes()).hexdigest();f=cv2.imread(str(source))
cv2.imwrite(str(tpl/'air_skeleton_barrel_top.png'),f[291:318,310:342])
manifest=[{'id':'air_skeleton_barrel_top','kind':'air','enabled':True,'file':'air_skeleton_barrel_top.png','threshold':0.74,'min_red_fraction':0.55,'anchor_offset':[-13,-6],'source':str(source.relative_to(ROOT)).replace('\\','/'),'source_sha256':digest,'source_crop':[310,291,342,318],'description':'Three red balloon tops of the observed skeleton barrel; labels and digits excluded. Limited air subtype only.','independent_validation_sources':['work/hog-validation/20260925-145226/observe-05-150337.png','work/hog-validation/20260925-181459/observe-02-182034.png'],'known_abstention_source':'work/hog-validation/20260925-172029/observe-03-172710.png'}]
(tpl/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
fixtures=REP/'tests'/'fixtures'/'cn_threats';fixtures.mkdir(exist_ok=True)
specs={'air_source.png':'20260926-005724/observe-01-005913.png','air_independent_bridge.png':'20260925-145226/observe-05-150337.png','air_independent_deep.png':'20260925-181459/observe-02-182034.png','air_unknown_pose.png':'20260925-172029/observe-03-172710.png','ordinary_single.png':'20260925-142322/observe-03-142941.png','ground_swarm.png':'20260926-005724/observe-05-010919.png','empty_and_friendly.png':'20260926-005724/observe-01-005817.png','red_single_highlight.png':'20260925-232740/play-03-fireball-before.png'}
for name,path in specs.items():shutil.copyfile(SRC/path,fixtures/name)
print('installed air subtype, source_sha256',digest)
