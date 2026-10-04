from pathlib import Path
import json,hashlib,shutil,sys
import cv2
ROOT=Path(r'D:\codex\CodexWork\clash'); REPO=ROOT/'py-clash-bot'
OUT=ROOT/'work/567-optimize/vision';RUN=ROOT/'work/567-validation/20260928-122306'
BANK=REPO/'pyclashbot/detection/reference_images/cn_567_threats'
FIX=REPO/'tests/fixtures/cn_567_threats'
BANK.mkdir(exist_ok=True);FIX.mkdir(exist_ok=True)
specs=[
 {'id':'567_ground_drill_torso','kind':'ground','heavy':True,'role':'ground_heavy','small':False,'domain':'ground',
  'source_path':RUN/'play-00-arrows-before.png','crop':[99,311,124,345],'anchor_offset':[-4,3],
  'tag_search_bbox':[-8,-30,22,-5],'threshold':.78,
  'heldout_path':RUN/'observe-01-122339.png','source_name':'ground_drill_source.png','heldout_name':'ground_drill_heldout.png',
  'description':'Visible drilling ground unit torso; one nearby non-source frame validates this pose. Does not generalize to ordinary Giant or Giant Skeleton.'},
 {'id':'567_air_baby_dragon_front','kind':'air','heavy':False,'role':'air','small':False,'domain':'air',
  'source_path':OUT/'04a276db5c97dc7a79e9d57c71cf9a19ea0e9916ca0b541f4b1719784353bb2e.png','crop':[322,230,341,252],'anchor_offset':[3,-8],
  'tag_search_bbox':[-20,-18,14,3],'threshold':.88,
  'heldout_path':OUT/'59e813acb866b5edd35d62095228eae2ac35ce293c184111e9386b4ef6543cb9.png',
  'source_name':'baby_dragon_source.png','heldout_name':'baby_dragon_heldout.png',
  'description':'Enemy baby dragon frontal head, with separately verified hostile white/gold level plaque. Different source and held-out capture; other wing/attack poses remain unknown.'},
]
log=[json.loads(line) for line in (ROOT/'outputs/cn-567-strategy.jsonl').read_text(encoding='utf8').splitlines() if line.strip()]
rows=[]
for s in specs:
 item={k:v for k,v in s.items() if k not in {'source_path','heldout_path','source_name','heldout_name','crop'}}
 item.update(enabled=True,role_recovery_only=True,file=s['id']+'.png')
 refs=[]
 for key,namekey in [('source_path','source_name'),('heldout_path','heldout_name')]:
  p=s[key];data=p.read_bytes();sha=hashlib.sha256(data).hexdigest()
  evidence=[]
  for e in log:
   for ek in ['evidence','evidence_before','evidence_after']:
    if e.get(ek,{}).get('sha256')==sha:evidence.append({'time':e['time'],'battle':e['battle'],'event':e['event'],'field':ek,'path':e[ek]['path'],'sha256':sha})
  assert evidence,(str(p),sha)
  dst=FIX/s[namekey];dst.write_bytes(data)
  refs.append({'path':dst.relative_to(REPO).as_posix(),'sha256':sha,'trace_evidence':evidence[0]})
 item['source']=refs[0]['path'];item['source_sha256']=refs[0]['sha256'];item['source_crop']=s['crop'];item['source_trace']=refs[0]['trace_evidence']
 item['independent_validation_sources']=[refs[1]]
 im=cv2.imread(str(s['source_path']));x1,y1,x2,y2=s['crop'];cv2.imwrite(str(BANK/item['file']),im[y1:y2,x1:x2])
 item['template_sha256']=hashlib.sha256((BANK/item['file']).read_bytes()).hexdigest()
 rows.append(item)
(BANK/'manifest.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
sys.path.insert(0,str(REPO))
from pyclashbot.detection.cn_threats import read_cn_threats
for path in FIX.glob('*.png'):
 print(path.name,read_cn_threats(cv2.imread(str(path)),[],include_567=True))
