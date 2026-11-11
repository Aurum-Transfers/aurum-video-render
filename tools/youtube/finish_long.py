#!/usr/bin/env python3
"""Resume a publish_long.py run that stopped AFTER the private insert (e.g. quotaExceeded).
usage: finish_long.py <video.json> <videoId> --mode public|schedule [--publish-at ISO] [--skip-captions]
Re-runs package (yt_<id> SubIDs) + landing check + operator scan + gate.py publish, then captions -> final update
(description + public/publishAt). Writes result.json; on any failure the video stays private."""
import argparse,datetime,json,os,subprocess,sys
T=os.path.dirname(os.path.abspath(__file__))
ap=argparse.ArgumentParser(); ap.add_argument('cfg'); ap.add_argument('vid'); ap.add_argument('--mode',required=True,choices=['public','schedule'])
ap.add_argument('--publish-at'); ap.add_argument('--skip-captions',action='store_true'); a=ap.parse_args()
D=os.path.dirname(os.path.abspath(a.cfg)); cfg=json.load(open(a.cfg)); RP=os.path.join(D,'result.json')
R=json.load(open(RP)) if os.path.exists(RP) else {}; R.update(resumed_by='finish_long.py',video_id=a.vid,url=f'https://youtu.be/{a.vid}')
def run(c): r=subprocess.run(c,capture_output=True,text=True); return r.returncode,(r.stdout+r.stderr)
def done(ok,why=''):
    R.update(ok=ok,why=why,ended=datetime.datetime.now().astimezone().isoformat(timespec='seconds')); json.dump(R,open(RP,'w'),indent=1); print(json.dumps({k:R.get(k) for k in ('ok','why','video_id','publish_at')})); sys.exit(0 if ok else 1)
if a.mode=='schedule' and not a.publish_at: done(False,'--publish-at required')
rc,o=run([sys.executable,f'{T}/yt.py','get','--id',a.vid]);
if rc: done(False,'get failed: '+o[-200:])
g=json.loads(next(l for l in o.splitlines() if l.startswith('{')))
if g['status']['privacyStatus']=='public': done(False,'already public; refuse')
rc,o=run([sys.executable,f'{T}/build_package.py',a.cfg,a.vid])
if rc: done(False,'package failed: '+o[-200:])
rc,o=run([sys.executable,f'{T}/landing_check.py',a.cfg]); R['landing']=o.strip()
if rc: done(False,'landing check failed (video stays private)')
desc=open(os.path.join(D,'description.txt')).read()
for bad in ('we operate','our drivers','our cars','aurum operates'):
    if bad in desc.lower(): done(False,'operator claim: '+bad)
if 'VIDEO_ID' in desc or 'pending' in desc: done(False,'placeholder SubID left')
rc,o=run(['python3','/workspace/ops/scripts/gate.py','publish','--bot','aurum-reels','--what',f"YouTube long {cfg['slug']} ({a.mode}, resume)"])
if rc: done(False,f'gate.py publish exit {rc}: {o}')
rc,o=run([sys.executable,f'{T}/thumb_gate.py',a.cfg,'--require-set','--id',a.vid])
if rc:  # hard gate (Marvin 11 Nov): designed Bali banner must be set before any publish/publishAt
    rc,o=run([sys.executable,f'{T}/set_thumb.py','--video-json',a.cfg,'--id',a.vid]); R['thumb']=o[-300:]
    if rc: done(False,'designed thumbnail not set (video stays private): '+o[-200:])
    rc,o=run([sys.executable,f'{T}/thumb_gate.py',a.cfg,'--require-set','--id',a.vid])
    if rc: done(False,'thumb gate: '+o[-200:])
if not a.skip_captions:
    rc,o=run([sys.executable,f'{T}/yt.py','caption','--id',a.vid,'--srt',os.path.join(D,cfg['srt'])]); R['captions']=o[-200:]
    if rc: done(False,'captions failed (video stays private)')
up={'snippet':{'title':cfg['title'],'description':desc,'tags':cfg['tags'],'categoryId':'19','defaultLanguage':'en','defaultAudioLanguage':'en'},
    'status':{'privacyStatus':'private','selfDeclaredMadeForKids':False,'containsSyntheticMedia':bool(cfg['synthetic']),'embeddable':True,'license':'youtube'}}
if a.mode=='public': up['status']['privacyStatus']='public'
else: up['status']['publishAt']=a.publish_at
mp=os.path.join(D,'meta-final.json'); json.dump(up,open(mp,'w'))
rc,o=run([sys.executable,f'{T}/yt.py','update','--id',a.vid,'--meta',mp])
if rc: done(False,'final update failed (video private): '+o[-300:])
R['status']=o.strip()[-600:]; R['publish_at']=a.publish_at
try:  # standing rule 11 Nov: free box copies that already have a hash-verified remote copy (non-fatal)
    rc2,o2=run([sys.executable,f'{T}/purge_verified.py','--offload-vultr','--slug',cfg['slug'],'--quiet']); R['purge']=o2.strip()[-300:]
except Exception as e: R['purge']=f'purge skipped: {e}'
done(True)
