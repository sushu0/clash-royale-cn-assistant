from pathlib import Path
from collections import Counter
import json,hashlib,cv2,numpy as np,sys
ROOT=Path(r'D:\codex\CodexWork\clash');BASE=ROOT/(sys.argv[1]if len(sys.argv)>1 else 'work/batch5/20260926-1535-baseline');OUT=BASE/'vision_audit'
events=[json.loads(x)for x in (BASE/'events.jsonl').read_text(encoding='utf8').splitlines()if x.strip()];selected=[];bad=[];verified=0
for i,e in enumerate(events):
    for k,v in e.get('captured_evidence',{}).items():
        if not v['status'].startswith('verified_') or hashlib.sha256(Path(v['frozen_path']).read_bytes()).hexdigest()!=v['expected_sha256']:bad.append([i,k])
        else:verified+=1
    if e['event']=='play'and not e['confirmed']:
        for key in ('evidence_before','evidence_after'):
            selected.append((i,e,key,e['captured_evidence'][key]['frozen_path']))
    elif e['event']=='screen_unknown':selected.append((i,e,'evidence',e['captured_evidence']['evidence']['frozen_path']))
for page in range((len(selected)+11)//12):
    s=np.full((3*350,4*220,3),245,np.uint8)
    for j,(i,e,key,file)in enumerate(selected[page*12:(page+1)*12]):
        f=cv2.imread(file);p=cv2.resize(f,(210,317));x=j%4*220;y=j//4*350;s[y:y+317,x:x+210]=p;card=e.get('decision',{}).get('card',e['event']);cv2.putText(s,f'{i}:{card}:{key[-5:]}',(x,y+331),cv2.FONT_HERSHEY_SIMPLEX,.37,(0,0,0),1);cv2.putText(s,e['time'][-8:],(x,y+345),cv2.FONT_HERSHEY_SIMPLEX,.35,(0,0,0),1)
    cv2.imwrite(str(OUT/f'confirmation-transition-{page}.jpg'),s)
summary={'events':len(events),'verified_evidence_references':verified,'hash_bad':bad,'event_counts':dict(Counter(e['event']for e in events)),'unconfirmed':[{'i':i,'time':e['time'],'battle':e['battle'],'card':e['decision']['card'],'spent':e['observed_spend'],'after_elixir':e['after_elixir']}for i,e in enumerate(events)if e['event']=='play'and not e['confirmed']],'after_images_and_transitions':len(selected)}
(OUT/'aux-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(summary,ensure_ascii=True,indent=2))
