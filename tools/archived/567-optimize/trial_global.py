exec(open(r'D:\codex\CodexWork\clash\work\567-optimize\trial_vision.py',encoding='utf8').read().split('frames=[]')[0])
trial=[
 ('heavy_giant',OUT/'a16385f1e4b53587f455c606031b88612f49c9e9fa8478813626a074edfa8b5d.png',(284,322),(286,314,316,343)),
 ('heavy_skeleton',RUN/'observe-04-123112.png',(105,242),(93,235,118,256)),
 ('light_ranged',RUN/'observe-04-123112.png',(123,249),(114,256,130,273)),
]
frames=[]
for p in [*RUN.glob('observe-*.png'),*RUN.glob('opening-*.png'),*RUN.glob('play-*.png'),*OUT.glob('[0-9a-f]'*64+'.png'),*list((ROOT/'py-clash-bot/tests/fixtures').rglob('*.png'))]:
 im=cv2.imread(str(p))
 if im is None or im.shape!=(633,419,3):continue
 frames.append((p,im,cv2.cvtColor(im,cv2.COLOR_BGR2GRAY)))
res=[]
for name,p,anchor,bbox in trial:
 src=cv2.imread(str(p));x1,y1,x2,y2=bbox;template=src[y1:y2,x1:x2];th,tw=template.shape[:2];gray=cv2.cvtColor(template,cv2.COLOR_BGR2GRAY)
 matches=[]
 for path,im,imgray in frames:
   scores=np.minimum(cv2.matchTemplate(im[200:460,50:370],template,cv2.TM_CCOEFF_NORMED),cv2.matchTemplate(imgray[200:460,50:370],gray,cv2.TM_CCOEFF_NORMED))
   _,score,_,(mx,my)=cv2.minMaxLoc(scores)
   if score>.55: matches.append({'score':score,'path':str(path),'anchor':[mx+50-(x1-anchor[0]),my+200-(y1-anchor[1])],'bbox':[mx+50,my+200,tw,th]})
 matches.sort(key=lambda x:x['score'],reverse=True)
 res.append({'name':name,'source':str(p),'crop':bbox,'anchor':anchor,'matches':matches})
(OUT/'trial-global.json').write_text(json.dumps(res,indent=2),encoding='utf8')
for r in res:
 print(r['name'],[(round(m['score'],3),Path(m['path']).name,m['anchor']) for m in r['matches'][:15]])
 tiles=[]
 for m in r['matches'][:24]:
  im=cv2.imread(m['path']);ex,ey=m['anchor'];xx1,yy1=max(0,ex-50),max(0,ey-35);xx2,yy2=min(419,ex+60),min(633,ey+70)
  crop=im[yy1:yy2,xx1:xx2];crop=cv2.resize(crop,(220,210),interpolation=cv2.INTER_NEAREST)
  tile=np.zeros((240,220,3),np.uint8);tile[30:]=crop;cv2.putText(tile,f"{len(tiles)} {m['score']:.3f} {ex},{ey}",(3,18),0,.5,(255,255,255),1);tiles.append(tile)
 if tiles:
  while len(tiles)%6:tiles.append(np.zeros_like(tiles[0]))
  cv2.imwrite(str(OUT/f"global-{r['name']}.png"),np.vstack([np.hstack(tiles[i:i+6]) for i in range(0,len(tiles),6)]))
