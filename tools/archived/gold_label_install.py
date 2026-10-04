from pathlib import Path
import cv2,json,shutil,hashlib
ROOT=Path(r'D:\codex\CodexWork\clash');REP=ROOT/'py-clash-bot';BASE=ROOT/'work'/'batch5'/'20260926-170957-candidate2';rows={r['i']:r for r in json.loads((BASE/'vision_audit'/'map.json').read_text(encoding='utf8'))}
folder=REP/'pyclashbot'/'detection'/'reference_images'/'cn_enemy_tags'/'gold';folder.mkdir(exist_ok=True);manifest=[]
for name,i,(x1,y1,x2,y2)in [('red_gold_14',61,(275,271,284,281)),('red_gold_16',65,(117,334,126,344))]:
    p=Path(rows[i]['file']);f=cv2.imread(str(p));cv2.imwrite(str(folder/(name+'.png')),f[y1:y2,x1:x2]);manifest.append({'file':name+'.png','source':str(p.relative_to(ROOT)).replace('\\','/'),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'crop':[x1,y1,x2,y2],'description':'Confirmed hostile red plaque with golden digits; number is not itself a side test.'})
(folder/'sources.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
fixtures=REP/'tests'/'fixtures'/'cn_battle_cues'
for name,i in [('gold_enemy_source14.png',61),('gold_enemy_source16.png',65),('gold_enemy_other_time.png',63),('gold_enemy_other_battle.png',179),('gold_friendly_and_towers.png',44)]:shutil.copyfile(rows[i]['file'],fixtures/name)
print('Created isolated gold digit template bank and real frame fixtures')
