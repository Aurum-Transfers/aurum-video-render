#!/usr/bin/env python3
"""One-command long-video publish for Aurum Reels.
Usage: publish_long.py <video_dir>/video.json --mode public|schedule [--publish-at ISO8601] [--dry-run]
Steps: gates pass (checks.json pass + sha) -> build package -> landing check (200s) -> gate.py publish ->
videos.insert private -> rebuild description with yt_<id> -> update -> thumbnail -> captions -> public or private+publishAt.
Any failure leaves the video private and writes result.json with the reason. Never prints secrets."""
import json,sys,os,subprocess,hashlib,argparse,datetime
T=os.path.dirname(os.path.abspath(__file__))
ap=argparse.ArgumentParser(); ap.add_argument('cfg'); ap.add_argument('--mode',required=True,choices=['public','schedule']); ap.add_argument('--publish-at'); ap.add_argument('--dry-run',action='store_true')
a=ap.parse_args(); D=os.path.dirname(os.path.abspath(a.cfg)); cfg=json.load(open(a.cfg)); R={'slug':cfg['slug'],'started':datetime.datetime.now().astimezone().isoformat(timespec='seconds')}
def done(ok,why=''):
    R.update(ok=ok,why=why,ended=datetime.datetime.now().astimezone().isoformat(timespec='seconds')); json.dump(R,open(os.path.join(D,'result.json'),'w'),indent=1); print(json.dumps(R)); sys.exit(0 if ok else 1)
def run(cmd): p=subprocess.run(cmd,capture_output=True,text=True); return p.returncode,(p.stdout+p.stderr).strip()
c=json.load(open(cfg['checks'])); failed=set(c.get('failed') or []); want_sha=c['sha256']
if cfg.get('checks_patch'):  # audio-only remix (video stream copied): re-measured gates must cover every CI failure
    pp=json.load(open(cfg['checks_patch']))['results'][os.path.basename(cfg['master'])]
    if not pp.get('all_pass') or pp.get('failed'): done(False,f"patched gates failed: {pp.get('failed')}")
    fixed={k for k,v in pp['audio_gates'].items() if v.get('pass')}
    failed-=fixed; want_sha=cfg['sha256']; R['checks_patch']=sorted(fixed)
if failed or not (c.get('pass') or cfg.get('checks_patch')): done(False,f"pipeline gates failed: {sorted(failed)}")
h=hashlib.sha256(open(cfg['master'],'rb').read()).hexdigest()
if h!=want_sha: done(False,'master sha256 does not match the gate record')
R['gates']='pass'; R['sha256']=h
for f in (cfg['thumb'],cfg['srt']):
    if not os.path.exists(os.path.join(D,f)): done(False,f'missing {f}')
rc,o=run([sys.executable,f'{T}/thumb_gate.py',a.cfg])  # designed banner required before any upload
if rc: done(False,'thumb gate (no upload): '+o[-200:])
rc,o=run([sys.executable,f'{T}/build_package.py',a.cfg]); 
if rc: done(False,'package: '+o)
rc,o=run([sys.executable,f'{T}/landing_check.py',a.cfg]); R['landing']=o
if rc: done(False,'landing check failed')
desc=open(os.path.join(D,'description.txt')).read()
for bad in ('we operate','our drivers','our cars','Aurum operates'):
    if bad.lower() in desc.lower(): done(False,'operator claim in description: '+bad)
rc,o=run(['python3','/workspace/ops/scripts/gate.py','publish','--bot','aurum-reels','--what',f"YouTube long {cfg['slug']} ({a.mode})"])
if rc: done(False,'gate.py publish exit '+str(rc)+': '+o)
if a.dry_run: done(True,'dry-run ok (nothing uploaded)')
meta={'snippet':{'title':cfg['title'],'description':desc.replace('{VIDEO_ID}','pending'),'tags':cfg['tags'],'categoryId':'19','defaultLanguage':'en','defaultAudioLanguage':'en'},
      'status':{'privacyStatus':'private','selfDeclaredMadeForKids':False,'containsSyntheticMedia':bool(cfg['synthetic']),'embeddable':True,'license':'youtube'}}
mp=os.path.join(D,'meta-insert.json'); json.dump(meta,open(mp,'w'))
rc,o=run([sys.executable,f'{T}/yt.py','insert','--file',cfg['master'],'--meta',mp])
if rc: done(False,'upload failed: '+o[-400:])
vid=json.loads(o.strip().splitlines()[-1])['id']; R['video_id']=vid; R['url']=f'https://youtu.be/{vid}'
rc,o=run([sys.executable,f'{T}/build_package.py',a.cfg,vid])
desc=open(os.path.join(D,'description.txt')).read()
up={'snippet':{**meta['snippet'],'description':desc},'status':dict(meta['status'])}
rc,o=run([sys.executable,f'{T}/thumb_gate.py',a.cfg,'--require-set','--id',vid])
if rc:  # hard gate (Marvin 11 Nov): designed Bali banner must be set before any publish/publishAt
    rc,o=run([sys.executable,f'{T}/set_thumb.py','--video-json',a.cfg,'--id',vid]); R['thumb']=o[-300:]
    if rc: done(False,'designed thumbnail not set (video stays private): '+o[-200:])
    rc,o=run([sys.executable,f'{T}/thumb_gate.py',a.cfg,'--require-set','--id',vid])
    if rc: done(False,'thumb gate: '+o[-200:])
rc,o=run([sys.executable,f'{T}/yt.py','caption','--id',vid,'--srt',os.path.join(D,cfg['srt'])]); R['captions']=o[-200:]
if rc: done(False,'captions failed (video stays private)')
if a.mode=='public': up['status']['privacyStatus']='public'
else: up['status']['publishAt']=a.publish_at
json.dump(up,open(mp,'w')); rc,o=run([sys.executable,f'{T}/yt.py','update','--id',vid,'--meta',mp])
if rc: done(False,'final update failed (video private): '+o[-300:])
R['status']=o; R['publish_at']=a.publish_at
done(True)
