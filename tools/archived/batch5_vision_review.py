from pathlib import Path
import json,hashlib,cv2,numpy as np,sys
ROOT=Path(r'D:\codex\CodexWork\clash');BASE=ROOT/(sys.argv[1]if len(sys.argv)>1 else 'work/batch5/20260926-1535-baseline');FIRST=int(sys.argv[2])if len(sys.argv)>2 else 12;OUT=BASE/'vision_audit';OUT.mkdir(exist_ok=True)
events=[]
for line in (BASE/'events.jsonl').read_text(encoding='utf8').splitlines():
    try:events.append(json.loads(line))
    except json.JSONDecodeError:pass
records=[];bad=[]
for i,e in enumerate(events):
    key='evidence_before' if e['event']=='play'else'evidence'
    cap=e.get('captured_evidence',{}).get(key)
    if not cap:continue
    if not cap['status'].startswith('verified_'):bad.append({'i':i,'status':cap['status']});continue
    p=Path(cap['frozen_path']);digest=hashlib.sha256(p.read_bytes()).hexdigest()
    if digest!=cap['expected_sha256']:bad.append({'i':i,'status':'frozen_hash_changed'});continue
    records.append({'i':i,'battle':e['battle'],'time':e['time'],'event':e['event'],'file':str(p),'source_line':e['capture_source_line'],'data':e})
for battle in range(FIRST,FIRST+5):
    visual=[r for r in records if r['battle']==battle and r['event']in('play','observe','elite_ability')]
    for page in range((len(visual)+15)//16):
        sheet=np.full((4*350,4*220,3),245,np.uint8)
        for cell,r in enumerate(visual[page*16:(page+1)*16]):
            f=cv2.imread(r['file']);e=r['data']
            for x,y in e.get('cues',{}).get('enemies',[]):cv2.circle(f,(x,y-16),8,(0,255,0),1)
            if e.get('decision')and'point'in e['decision']:
                p=e['decision']['point'];cv2.drawMarker(f,tuple(p),(0,0,255),cv2.MARKER_CROSS,14,2)
            tile=cv2.resize(f,(210,317));x=cell%4*220;y=cell//4*350;sheet[y:y+317,x:x+210]=tile
            d=e.get('decision',{});txt=f'{r["i"]} {d.get("card",r["event"])} n={len(e.get("cues",{}).get("enemies",[]))}'
            cv2.putText(sheet,txt,(x,y+330),cv2.FONT_HERSHEY_SIMPLEX,.4,(0,0,0),1)
            cv2.putText(sheet,r['time'][-8:],(x,y+344),cv2.FONT_HERSHEY_SIMPLEX,.35,(0,0,0),1)
        cv2.imwrite(str(OUT/f'battle-{battle}-{page}.jpg'),sheet)
(OUT/'map.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'events':len(events),'verified_reviewable':len(records),'bad':bad,'ends':[{'battle':r['battle'],'result':r['result'],'time':r['time']}for r in events if r['event']=='battle_end'],'visual_counts':{b:sum(r['battle']==b and r['event']in('play','observe','elite_ability')for r in records)for b in range(FIRST,FIRST+5)},'special':[{'i':r['i'],'battle':r['battle'],'event':r['event'],'file':r['file']}for r in records if r['event']in('battle_end','reward','batch_complete')]},indent=2))
