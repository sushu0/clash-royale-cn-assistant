"""Read-only, offline feature probes; never imported by the running bot."""
from pathlib import Path
import cv2,json,hashlib,sys
import numpy as np
ROOT=Path(r'D:\codex\CodexWork\clash');REPO=ROOT/'py-clash-bot';OUT=Path(__file__).parent
sys.path.insert(0,str(REPO))
from pyclashbot.bot.coords import CN_HOG_FRIENDLY_TOWER_BOXES
from pyclashbot.detection.cn_battle_cues import read_cn_battle_cues
from pyclashbot.detection.cn_threats import read_cn_threats
VS=ROOT/'work/567-optimize/vision';FIX=REPO/'tests/fixtures';RUN=ROOT/'work/567-validation/20260928-122306'
events=json.loads((VS/'verified_events.json').read_text())
def observed(name):return next(x for x in events if Path(x['evidence']['path']).name==name)
cases=[]
for name,anchor,label in [
 ('recent-observe-43.png',(284,322),'heavy_source'),
 ('recent-observe-42.png',(284,221),'heavy_heldout_11s_earlier'),
 ('recent-observe-48.png',(116,340),'heavy_heldout_separate_push_52s'),
 ('recent-observe-55.png',(319,354),'uncertain_helmet_bare_arm_tower_occlusion'),
 ('recent-observe-63.png',(167,416),'uncertain_helmet_bare_arm_king_occlusion'),
 ('recent-observe-16.png',(243,425),'uncertain_helmet_bare_arm_king_other_battle'),
]:
 e=observed(name);p=Path(e['frozen_path']);assert hashlib.sha256(p.read_bytes()).hexdigest()==e['evidence']['sha256']
 cases.append({'id':label,'path':str(p),'anchor':anchor,'time':e['time'],'battle':e['battle'],'sha256':e['evidence']['sha256']})
for name,anchor,label in [
 ('observe-03-122710.png',(328,237),'air_mega_minion_blue_team_morphology_control'),
 ('observe-04-123112.png',(123,249),'light_ranged_ground'),
 ('play-00-arrows-before.png',(88,259),'air_baby_dragon_enemy'),
 ('observe-01-122319.png',(118,385),'own_princess_tower_body'),
 ('observe-01-122319.png',(208,430),'own_king_tower_body'),
]:
 p=RUN/name;cases.append({'id':label,'path':str(p),'anchor':anchor,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
for folder,name in [('cn_threats','balloon_envelope_source.png'),('cn_threats','air_source.png'),('cn_threats','air_independent_deep.png'),('cn_567_threats','baby_dragon_heldout.png')]:
 p=FIX/folder/name;im=cv2.imread(str(p));cu=read_cn_battle_cues(im,include_567=True)
 for r in cu['threats']:
  if r['kind']=='air':cases.append({'id':'air_'+name,'path':str(p),'anchor':(r['x'],r['y']),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
def features(im,anchor,clip_towers):
 ex,ey=anchor;x1,y1=max(0,ex-12),max(0,ey-8);x2,y2=min(419,ex+42),min(510,ey+46)
 roi=im[y1:y2,x1:x2];hsv=cv2.cvtColor(roi,cv2.COLOR_BGR2HSV);hh,ss,vv=cv2.split(hsv)
 masks={'skin_narrow':(hh>=4)&(hh<=22)&(ss>=60)&(ss<=210)&(vv>=90),
 'skin_peach':(hh<=15)&(ss>=55)&(ss<=180)&(vv>=150),
 'skin_wide':(hh<=28)&(ss>=45)&(ss<=235)&(vv>=90),
 'dark_armor':(vv>=25)&(vv<=115)&(ss<=180)}
 result={}
 for name,mask in masks.items():
  mask=(mask.astype(np.uint8)*255)
  if clip_towers:
   for box in CN_HOG_FRIENDLY_TOWER_BOXES.values():
    ax,ay,bx,by=box;mask[max(0,ay-y1):min(y2-y1,by-y1),max(0,ax-x1):min(x2-x1,bx-x1)]=0 if (bx>x1 and by>y1 and ax<x2 and ay<y2) else mask[max(0,ay-y1):min(y2-y1,by-y1),max(0,ax-x1):min(x2-x1,bx-x1)]
  num,_,stats,_=cv2.connectedComponentsWithStats(mask,8)
  biggest=max(stats[1:],key=lambda s:s[4]) if num>1 else np.zeros(5,dtype=int)
  result[name]={'pixels':int(np.count_nonzero(mask)),'component_area':int(biggest[4]),'width':int(biggest[2]),'height':int(biggest[3])}
 return result
for c in cases:
 im=cv2.imread(c['path']);c['unmasked']=features(im,c['anchor'],False);c['tower_masked']=features(im,c['anchor'],True)
(OUT/'feature-probes.json').write_text(json.dumps(cases,indent=2),encoding='utf8')
for c in cases:print(c['id'],c['unmasked'],c['tower_masked'])
# Across the frozen replay bank, measure highest raw skin component and save
# a reviewable contact sheet. This is a counterexample search, not training.
ranked=[]
for path in VS.glob('[0-9a-f]'*64+'.png'):
 im=cv2.imread(str(path));cu=read_cn_battle_cues(im)
 for anchor in sorted(set(tuple(p) for p in cu['enemies']+cu['far_warnings'])):
  f=features(im,anchor,True);m=f['skin_peach']
  if m['component_area']>=180:ranked.append({'path':str(path),'anchor':anchor,'features':f})
ranked.sort(key=lambda x:x['features']['skin_peach']['component_area'],reverse=True)
(OUT/'large-skin-candidates.json').write_text(json.dumps(ranked,indent=2),encoding='utf8')
tiles=[]
for i,r in enumerate(ranked[:36]):
 im=cv2.imread(r['path']);ex,ey=r['anchor'];x1,y1=max(0,ex-35),max(0,ey-30);x2,y2=min(419,ex+65),min(510,ey+65)
 crop=cv2.resize(im[y1:y2,x1:x2],(200,190),interpolation=cv2.INTER_NEAREST);tile=np.zeros((215,200,3),np.uint8);tile[25:]=crop
 cv2.putText(tile,f"{i}: {r['features']['skin_peach']['component_area']} {ex},{ey}",(3,18),0,.44,(255,255,255),1);tiles.append(tile)
if tiles:
 while len(tiles)%6:tiles.append(np.zeros_like(tiles[0]))
 cv2.imwrite(str(OUT/'large-skin-candidates.png'),np.vstack([np.hstack(tiles[i:i+6]) for i in range(0,len(tiles),6)]))
