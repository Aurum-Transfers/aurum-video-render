#!/usr/bin/env python3
"""Aurum Reels YouTube helper. Never prints secrets. Token: /home/box/.secrets/aurum-reels/youtube_token.json"""
import json, sys, argparse
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
TOK='/home/box/.secrets/aurum-reels/youtube_token.json'
def yt():
    c=Credentials.from_authorized_user_file(TOK)
    if not c.valid:
        c.refresh(Request())
        d=json.load(open(TOK)); d['token']=c.token; d['expiry']=c.expiry.isoformat()+'Z' if c.expiry else None
        json.dump(d,open(TOK,'w'))
    return build('youtube','v3',credentials=c,cache_discovery=False)
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('cmd')
    ap.add_argument('--file'); ap.add_argument('--meta'); ap.add_argument('--id'); ap.add_argument('--thumb'); ap.add_argument('--srt')
    a=ap.parse_args(); y=yt()
    if a.cmd=='whoami':
        r=y.channels().list(part='snippet,status',mine=True).execute()
        print(json.dumps([{'id':i['id'],'title':i['snippet']['title'],'status':i.get('status')} for i in r.get('items',[])]))
    elif a.cmd=='insert':
        m=json.load(open(a.meta))
        req=y.videos().insert(part='snippet,status',body=m,media_body=MediaFileUpload(a.file,chunksize=16*1024*1024,resumable=True,mimetype='video/mp4'))
        resp=None
        while resp is None:
            st,resp=req.next_chunk()
            if st: print('progress',int(st.progress()*100),flush=True)
        print(json.dumps({'id':resp['id'],'status':resp['status']}))
    elif a.cmd=='update':
        m=json.load(open(a.meta)); m['id']=a.id
        parts=','.join(k for k in m if k!='id')
        r=y.videos().update(part=parts,body=m).execute(); print(json.dumps({'id':r['id'],'status':r.get('status')}))
    elif a.cmd=='thumb':
        r=y.thumbnails().set(videoId=a.id,media_body=MediaFileUpload(a.thumb)).execute(); print('thumb ok')
    elif a.cmd=='caption':
        r=y.captions().insert(part='snippet',body={'snippet':{'videoId':a.id,'language':'en','name':'English','isDraft':False}},media_body=MediaFileUpload(a.srt,mimetype='application/octet-stream')).execute(); print('caption ok',r['id'])
    elif a.cmd=='list':  # every upload on the channel (channels 1u + playlistItems 1u/page + videos 1u/50)
        up=y.channels().list(part='contentDetails',mine=True).execute()['items'][0]['contentDetails']['relatedPlaylists']['uploads']
        ids=[];tok=None
        while True:
            r=y.playlistItems().list(part='contentDetails',playlistId=up,maxResults=50,pageToken=tok).execute()
            ids+=[i['contentDetails']['videoId'] for i in r['items']]; tok=r.get('nextPageToken')
            if not tok: break
        out=[]
        for k in range(0,len(ids),50):
            r=y.videos().list(part='snippet,status,contentDetails',id=','.join(ids[k:k+50])).execute()
            for i in r['items']:
                th=i['snippet'].get('thumbnails',{}); best=(th.get('maxres') or th.get('standard') or th.get('high') or {}).get('url')
                out.append({'id':i['id'],'title':i['snippet']['title'],'privacy':i['status']['privacyStatus'],'publishAt':i['status'].get('publishAt'),
                            'published':i['snippet'].get('publishedAt'),'duration':i['contentDetails']['duration'],'thumb':best})
        print(json.dumps(out))
    elif a.cmd=='get':
        r=y.videos().list(part='snippet,status,contentDetails,processingDetails',id=a.id).execute()
        i=r['items'][0]; print(json.dumps({'title':i['snippet']['title'],'status':i['status'],'duration':i['contentDetails']['duration'],'processing':i.get('processingDetails',{}).get('processingStatus'),'subids':i['snippet']['description'].count('yt_'+a.id),'placeholder':('VIDEO_ID' in i['snippet']['description'] or 'pending' in i['snippet']['description']),'line1':i['snippet']['description'].splitlines()[0],'viplounges':'viplounges' in i['snippet']['description'].lower(),'desc_len':len(i['snippet']['description'])}))
main()
