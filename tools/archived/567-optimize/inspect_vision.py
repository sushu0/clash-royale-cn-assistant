from pathlib import Path
import hashlib,json,sys
import cv2
import numpy as np
ROOT=Path(r'D:\codex\CodexWork\clash')
sys.path.insert(0,str(ROOT/'py-clash-bot'))
from pyclashbot.detection.cn_battle_cues import read_cn_battle_cues
OUT=ROOT/'work/567-optimize/vision'
OUT.mkdir(parents=True,exist_ok=True)
lines=(ROOT/'outputs/cn-567-strategy.jsonl').read_text(encoding='utf-8').splitlines()
events=[json.loads(line) for line in lines if line.strip()]
matching=[]
for e in events:
    if e.get('event')!='observe' or e.get('battle',0)<13: continue
    ev=e.get('evidence',{}); p=Path(ev.get('path',''))
    if not p.is_file():continue
    data=p.read_bytes(); h=hashlib.sha256(data).hexdigest()
    if h!=ev.get('sha256'):continue
    dst=OUT/(h+'.png')
    if not dst.exists():dst.write_bytes(data)
    e['frozen_path']=str(dst)
    matching.append(e)
(OUT/'verified_events.json').write_text(json.dumps(matching,indent=2),encoding='utf-8')
for batch in range(0,len(matching),16):
    tiles=[]
    for e in matching[batch:batch+16]:
        im=cv2.imread(e['frozen_path'])
        board=im[210:490].copy()
        for ex,ey in e['cues']['enemies']:
            cv2.circle(board,(ex,ey-210),4,(0,255,255),1)
        tile=np.zeros((310,419,3),np.uint8)
        tile[30:]=board
        cv2.putText(tile,f"B{e['battle']} {e['time'][11:]} {Path(e['evidence']['path']).name}",(3,17),cv2.FONT_HERSHEY_SIMPLEX,.42,(255,255,255),1)
        tiles.append(tile)
    while len(tiles)%4:tiles.append(np.zeros_like(tiles[0]))
    cv2.imwrite(str(OUT/f'board-{batch:03}.jpg'),np.vstack([np.hstack(tiles[i:i+4]) for i in range(0,len(tiles),4)]))
print(json.dumps({'verified':len(matching),'sheets':[str(p) for p in OUT.glob('board*.jpg')]}))
