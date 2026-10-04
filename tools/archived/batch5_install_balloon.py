from pathlib import Path
import cv2,json,hashlib,shutil
ROOT=Path(r'D:\codex\CodexWork\clash');REP=ROOT/'py-clash-bot';BASE=ROOT/'work'/'batch5'/'20260926-1535-baseline';OUT=BASE/'vision_audit';records=json.loads((OUT/'map.json').read_text(encoding='utf8'));rows={r['i']:r for r in records}
source=Path(rows[53]['file']);f=cv2.imread(str(source));folder=REP/'pyclashbot'/'detection'/'reference_images'/'cn_threats';template='air_balloon_envelope.png';cv2.imwrite(str(folder/template),f[305:343,289:331])
manifest=json.loads((folder/'manifest.json').read_text(encoding='utf8'));assert not any(x['id']=='air_balloon_envelope'for x in manifest)
manifest.append({'id':'air_balloon_envelope','kind':'air','enabled':True,'file':template,'threshold':0.78,'min_red_fraction':0.60,'anchor_offset':[-12,-12],'source':str(source.relative_to(ROOT)).replace('\\','/'),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'source_crop':[289,305,331,343],'description':'Observed single red netted balloon envelope; excludes level digits and basket. Only this visual subtype is calibrated.'})
(folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
fixtures=REP/'tests'/'fixtures'/'cn_threats'
for name,index in (('balloon_envelope_source.png',53),('balloon_envelope_approaching.png',52),('balloon_envelope_under_damage.png',54),('balloon_envelope_second_push.png',68),('balloon_envelope_unknown_angle.png',51)):
    shutil.copyfile(rows[index]['file'],fixtures/name)
shutil.copyfile(rows[54]['file'],REP/'tests'/'fixtures'/'cn_battle_cues'/'friendly_tower_trim_false_tag.png')
shutil.copyfile(rows[5]['file'],REP/'tests'/'fixtures'/'cn_battle_cues'/'real_enemies_at_friendly_tower.png')
print('Added calibrated ordinary balloon envelope; preserved existing template records')
