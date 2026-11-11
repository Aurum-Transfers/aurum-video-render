#!/usr/bin/env python3
"""Independent public-side verifier. verify_publish.py <video.json> <videoId> [--expect public|scheduled]
Uses only the public API key + public URLs (never the OAuth token). Writes <dir>/verify-<id>.json; exit 0 = pass."""
import json,sys,os,urllib.request,datetime
cfgp,vid=sys.argv[1],sys.argv[2]; exp=sys.argv[sys.argv.index('--expect')+1] if '--expect' in sys.argv else 'public'
D=os.path.dirname(os.path.abspath(cfgp)); cfg=json.load(open(cfgp))
key=open('/home/box/.secrets/aurum-reels/youtube_api_key.txt').read().strip()
def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=30) as r: return r.status,r.read().decode('utf-8','replace')
    except urllib.error.HTTPError as e: return e.code,''
st,b=get(f'https://www.googleapis.com/youtube/v3/videos?part=snippet,status,contentDetails&id={vid}&key={key}')
items=json.loads(b).get('items',[]) if st==200 else []
res={'video_id':vid,'checked_at':datetime.datetime.now().astimezone().isoformat(timespec='seconds'),'expect':exp,'checks':{}}
C=res['checks']
if exp=='public':
    C['api_public']=bool(items) and items[0]['status']['privacyStatus']=='public'
    d=items[0]['snippet']['description'] if items else ''
    C['title_match']=bool(items) and items[0]['snippet']['title']==cfg['title']
    n=sum(len(s['links']) for s in cfg['sections'])
    C['subids_filled']=d.count(f'yt_{vid}')==n and '{VIDEO_ID}' not in d and 'yt_pending' not in d
    C['disclosure_line1']=d.startswith('Aurum Transfers earns a commission if you book through links below, at no extra cost to you.')
    C['oembed_200']=get(f'https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json')[0]==200
    res['published_at']=items[0]['snippet'].get('publishedAt') if items else None
else:
    C['not_public_yet']=not items  # private/scheduled videos are invisible to the public API
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from thumb_gate import check as _tg
C['designed_thumb_set']=_tg(cfgp,True,vid) is None  # Bali banner recorded, 1280x720 <2MB, sha matches, set OK on this id
res['pass']=all(C.values())
out=os.path.join(D,f'verify-{vid}.json'); json.dump(res,open(out,'w'),indent=1); print(json.dumps(res)); sys.exit(0 if res['pass'] else 1)
