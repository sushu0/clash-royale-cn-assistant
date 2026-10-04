from pathlib import Path
import cv2,json,hashlib,shutil
ROOT=Path(r'D:\codex\CodexWork\clash');REP=ROOT/'py-clash-bot';BASE=ROOT/'work'/'batch5'/'20260926-161656-candidate';rows={r['i']:r for r in json.loads((BASE/'vision_audit'/'map.json').read_text(encoding='utf8'))}
source=Path(rows[90]['file']);folder=REP/'pyclashbot'/'detection'/'reference_images'/'cn_threats';f=cv2.imread(str(source));cv2.imwrite(str(folder/'air_balloon_envelope_early_pose.png'),f[211:249,96:138])
manifest=json.loads((folder/'manifest.json').read_text(encoding='utf8'));assert not any(r.get('file')=='air_balloon_envelope_early_pose.png'for r in manifest)
manifest.append({'id':'air_balloon_envelope','kind':'air','enabled':True,'early_only':True,'file':'air_balloon_envelope_early_pose.png','threshold':0.78,'min_red_fraction':0.60,'anchor_offset':[-21,-13],'source':str(source.relative_to(ROOT)).replace('\\','/'),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'source_crop':[96,211,138,249],'description':'Different early balloon pose from event 90; event 91 is held out, not a template source. Early ROI only, with separate red numeral verification.'})
(folder/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf8')
fixtures=REP/'tests'/'fixtures'/'cn_threats'
for name,i in (('early_balloon_pose_source.png',90),('early_balloon_crossing_heldout.png',91),('early_balloon_first_push_heldout.png',62),('early_balloon_second_push_heldout.png',78)):
    shutil.copyfile(rows[i]['file'],fixtures/name)
print('Added early-only pose; event91 remains held out')
