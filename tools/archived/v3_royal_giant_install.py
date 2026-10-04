from pathlib import Path
import cv2,json,hashlib,shutil
ROOT=Path(r'D:\codex\CodexWork\clash');SRC=ROOT/'work'/'hog-validation'/'20260926-122831';OUT=ROOT/'work'/'v3-royal-giant';REP=ROOT/'py-clash-bot'
folder=REP/'pyclashbot'/'detection'/'reference_images'/'cn_threats';manifest=json.loads((folder/'manifest.json').read_text(encoding='utf8'))
for filename,tpl_name in (('observe-01-122911.png','rush_royal_giant_head.png'),('play-02-musketeer-before.png','rush_royal_giant_head_recoil.png')):
    source=SRC/filename;b=source.read_bytes();digest=hashlib.sha256(b).hexdigest();(OUT/(source.stem+'-source.png')).write_bytes(b);f=cv2.imdecode(__import__('numpy').frombuffer(b,__import__('numpy').uint8),cv2.IMREAD_COLOR)
    cv2.imwrite(str(folder/tpl_name),f[270:294,296:330])
    manifest.append({'id':'rush_royal_giant_head','kind':'rush','enabled':True,'file':tpl_name,'threshold':0.88,'anchor_offset':[4,-8],'source':str(source.relative_to(ROOT)).replace('\\','/'),'source_sha256':digest,'source_crop':[296,270,330,294],'description':'Observed Royal Giant orange beard, head and chainmail shoulders. Excludes level digits/health bar and muzzle. Fixed current poses only.'})
(folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
fixtures=REP/'tests'/'fixtures'/'cn_threats'
for dst,src in (('royal_giant_source.png','observe-01-122911.png'),('royal_giant_recoil_source.png','play-02-musketeer-before.png'),('royal_giant_independent_fire.png','play-03-fireball-before.png'),('royal_giant_independent_after.png','play-02-musketeer-after.png'),('royal_giant_independent_later.png','play-04-log-before.png')):
    shutil.copyfile(SRC/src,fixtures/dst)
print('manifest records',len(manifest))
