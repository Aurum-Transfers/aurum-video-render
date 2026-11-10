"""upload: YouTube Data API v3, PRIVATE only. Never sets public; never prints tokens or keys.

Long video and each Short: videos.insert (resumable) -> thumbnails.set (long) -> captions.insert
-> videos.update with the final description (SubID yt_<videoId>).
"""
from __future__ import annotations

import os
from pathlib import Path

from .common import PhaseError, load_json, log, save_json, settings
from .description import build as build_description
from .render import out_name
from .script import units

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl"]
PRIVACY = "private"  # hard rule: never public, never unlisted


def video_body(title: str, description: str, tags: list[str], cfg: dict) -> dict:
    body = {
        "snippet": {"title": title[:100], "description": description, "tags": tags,
                    "categoryId": cfg["youtube"]["categoryId"], "defaultLanguage": cfg["youtube"]["defaultLanguage"],
                    "defaultAudioLanguage": cfg["youtube"]["defaultLanguage"]},
        "status": {"privacyStatus": PRIVACY, "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True,
                   "embeddable": True},
    }
    assert_private(body)
    return body


def assert_private(body: dict) -> None:
    if body.get("status", {}).get("privacyStatus") != "private":
        raise PhaseError("refusing upload: privacyStatus must be 'private'")


def client():
    token = os.environ.get("AURUM_YT_TOKEN")
    if not token or not Path(token).exists():
        raise PhaseError("AURUM_YT_TOKEN not set or file missing; not uploading")
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(token, SCOPES)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _insert(yt, path: Path, body: dict) -> str:
    from googleapiclient.http import MediaFileUpload

    assert_private(body)
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(str(path), chunksize=8 * 1024 * 1024, resumable=True,
                                                        mimetype="video/mp4"))
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            log(f"upload {path.name}: {int(status.progress() * 100)}%")
    return resp["id"]


def run_phase(ctx) -> dict:
    if ctx.no_upload:
        return {"skipped": "--no-upload"}
    if not os.environ.get("AURUM_YT_TOKEN"):
        raise PhaseError("AURUM_YT_TOKEN not set; upload skipped (nothing uploaded)")
    from googleapiclient.http import MediaFileUpload

    cfg = settings()
    meta = load_json(ctx.paths.video / "video.json")
    state = load_json(ctx.paths.out / "upload.json", default={})
    yt = client()
    for unit in units(ctx.paths.video):
        if state.get(unit, {}).get("id"):
            log(f"{unit}: already uploaded as private ({state[unit]['id']}), skipping")
            continue
        m = meta["long"] if unit == "long" else meta["shorts"][unit]
        title = m["title"] if unit == "long" else f"{m['title']} #Shorts"
        body = video_body(title, build_description(ctx, unit), m.get("tags", meta.get("tags", [])), cfg)
        vid = _insert(yt, ctx.paths.out / out_name(unit, getattr(ctx, 'output_stem', None)), body)
        state[unit] = {"id": vid, "privacy": PRIVACY}
        save_json(ctx.paths.out / "upload.json", state)
        if unit == "long":
            thumb = ctx.paths.out / "thumb-1.png"
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb), mimetype="image/png")).execute()
        srt = ctx.paths.out / f"{unit}.srt"
        yt.captions().insert(part="snippet", body={"snippet": {"videoId": vid, "language": "en", "name": "English",
                                                               "isDraft": False}},
                             media_body=MediaFileUpload(str(srt), mimetype="application/octet-stream")).execute()
        final = video_body(title, build_description(ctx, unit, video_id=vid), body["snippet"]["tags"], cfg)
        final["id"] = vid
        yt.videos().update(part="snippet,status", body=final).execute()
        log(f"{unit}: uploaded PRIVATE as {vid}")
    return {u: v["id"] for u, v in state.items()}
