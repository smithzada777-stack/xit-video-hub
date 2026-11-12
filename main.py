import os
import shutil
import tempfile
import uuid
import asyncio
import unicodedata
import requests
from typing import Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import yt_dlp
try:
    import imageio_ffmpeg
    FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_PATH = None

from database import db
from youtube_service import (
    get_channel_info,
    fetch_videos_from_channel,
    get_real_video_formats,
    extract_subtitles_text
)
from ai_service import generate_viral_content

app = FastAPI(title="XIT Studio", version="1.0.0")

# Automatic keep-alive task so server never hibernates
async def keep_alive_loop():
    await asyncio.sleep(60) # wait for startup
    app_url = os.getenv("RENDER_EXTERNAL_URL", "https://xit-video-hub.onrender.com")
    ping_url = f"{app_url}/healthz"
    while True:
        try:
            requests.get(ping_url, timeout=10)
        except Exception:
            pass
        await asyncio.sleep(480) # ping every 8 minutes

async def auto_seed_default_channel():
    await asyncio.sleep(2)
    try:
        channels = db.get_channels()
        if not channels:
            default_url = "https://www.youtube.com/channel/UCoAnxQ-zx7r-HoccMErZnng"
            info = get_channel_info(default_url)
            if info:
                db.save_channel(info)
                videos = fetch_videos_from_channel(info["url"], info["id"], limit=150)
                if videos:
                    db.save_videos(videos)
    except Exception as e:
        print(f"Auto-seed error: {e}")

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(keep_alive_loop())
    asyncio.create_task(auto_seed_default_channel())

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory="templates")

# Schemas
class AddChannelRequest(BaseModel):
    url: str

class UpdateStatusRequest(BaseModel):
    status: str

class GenerateScriptRequest(BaseModel):
    title: str
    duration: int
    is_short: bool

# Anti-Sleep Endpoints
@app.get("/healthz")
@app.get("/ping")
async def health_check():
    return {"status": "ok", "app": "XIT Studio", "service": "alive", "ytdlp": yt_dlp.version.__version__}

# PWA Files
@app.get("/manifest.json")
async def manifest():
    return JSONResponse({
        "short_name": "XIT Studio",
        "name": "XIT Studio - Cortes & Roteiros Pro",
        "icons": [
            {
                "src": "https://api.dicebear.com/7.x/bottts/svg?seed=xitstudio",
                "type": "image/svg+xml",
                "sizes": "512x512"
            }
        ],
        "start_url": "/",
        "background_color": "#090d16",
        "theme_color": "#090d16",
        "display": "standalone",
        "orientation": "portrait"
    })

# Frontend Home
@app.get("/", response_class=HTMLResponse)
async def index():
    try:
        with open("templates/index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except Exception as e:
        return HTMLResponse(content=f"<h1>Erro ao carregar template: {str(e)}</h1>", status_code=500)

# API: Channels
@app.get("/api/channels")
async def get_channels():
    return db.get_channels()

@app.post("/api/channels")
async def add_channel(payload: AddChannelRequest):
    info = get_channel_info(payload.url)
    if not info:
        raise HTTPException(status_code=400, detail="Não foi possível encontrar o canal do YouTube.")
    
    db.save_channel(info)
    
    # Auto-fetch all recent/available videos
    videos = fetch_videos_from_channel(info["url"], info["id"], limit=150)
    if videos:
        db.save_videos(videos)

    return info

@app.delete("/api/channels/{channel_id}")
async def delete_channel(channel_id: str):
    db.delete_channel(channel_id)
    return {"status": "deleted"}

@app.post("/api/channels/{channel_id}/sync")
async def sync_channel(channel_id: str):
    channels = db.get_channels()
    target = next((c for c in channels if c["id"] == channel_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Canal não encontrado")
    
    videos = fetch_videos_from_channel(target["url"], channel_id, limit=200)
    if videos:
        db.save_videos(videos)
    return {"status": "synced", "count": len(videos)}

class UpdateNotesRequest(BaseModel):
    notes: str

@app.post("/api/channels/{channel_id}/notes")
async def update_channel_notes(channel_id: str, payload: UpdateNotesRequest):
    db.update_channel_notes(channel_id, payload.notes)
    return {"status": "ok", "notes": payload.notes}

@app.post("/api/channels/{channel_id}/favorite")
async def toggle_channel_favorite(channel_id: str):
    new_val = db.toggle_channel_favorite(channel_id)
    return {"status": "ok", "is_favorite": new_val}

# API: Videos
@app.get("/api/channels/{channel_id}/videos")
async def get_channel_videos(channel_id: str, filter_type: str = "all", status: str = "all", sort_order: str = "asc"):
    return db.get_videos(channel_id=channel_id, filter_type=filter_type, status=status, sort_order=sort_order)

@app.get("/api/channels/{channel_id}/stats")
async def get_channel_stats(channel_id: str):
    all_v = db.get_videos(channel_id=channel_id, filter_type="all", status="all_inclusive")
    total = len(all_v)
    shorts = len([v for v in all_v if v.get("is_short")])
    videos = total - shorts
    
    tag_counts = {"queue": 0, "pending": 0, "downloaded": 0, "editing": 0, "scripted": 0, "posted": 0}
    for v in all_v:
        v_tags = v.get("tags") or ["pending"]
        if isinstance(v_tags, str):
            v_tags = [t.strip() for t in v_tags.split(",") if t.strip()]
        for t in tag_counts.keys():
            if t in v_tags:
                tag_counts[t] += 1

    return {
        "total": total,
        "videos": videos,
        "shorts": shorts,
        "tags": tag_counts
    }

@app.get("/api/settings")
async def get_app_settings_endpoint():
    return db.get_app_settings()

@app.post("/api/settings")
async def save_app_settings_endpoint(payload: dict):
    current = db.get_app_settings()
    current.update(payload)
    db.save_app_settings(current)
    return current

@app.post("/api/videos/{video_id}/status")
async def update_status(video_id: str, payload: UpdateStatusRequest):
    db.update_video_status(video_id, payload.status)
    return {"status": "updated", "new_status": payload.status}

@app.get("/api/videos/{video_id}/formats")
async def get_formats(video_id: str):
    return get_real_video_formats(video_id)

class UpdateTagsRequest(BaseModel):
    tags: list[str]

class BatchDeleteRequest(BaseModel):
    ids: list[str]

class BatchTagsRequest(BaseModel):
    ids: list[str]
    tag: str

@app.post("/api/videos/{video_id}/tags")
async def update_video_tags_endpoint(video_id: str, payload: UpdateTagsRequest):
    db.update_video_tags(video_id, payload.tags)
    return {"status": "updated", "tags": payload.tags}

@app.delete("/api/videos/{video_id}")
async def delete_single_video(video_id: str):
    db.delete_video(video_id)
    return {"status": "deleted", "id": video_id}

@app.post("/api/videos/batch-delete")
async def batch_delete_videos(payload: BatchDeleteRequest):
    db.delete_videos(payload.ids)
    return {"status": "deleted", "count": len(payload.ids)}

@app.post("/api/videos/batch-tags")
async def batch_tags_videos(payload: BatchTagsRequest):
    db.batch_update_tags(payload.ids, payload.tag)
    return {"status": "updated", "count": len(payload.ids)}

# API: Script Generation (with Anti-Repetition)
@app.post("/api/videos/{video_id}/generate-script")
async def generate_script(video_id: str, payload: GenerateScriptRequest):
    # Check if already generated
    cached = db.get_script_by_video(video_id)
    if cached:
        db.update_video_status(video_id, "scripted")
        return cached

    # Get history of past titles/hooks so it won't repeat
    past_scripts = db.get_past_script_titles(limit=15)
    subs = extract_subtitles_text(video_id)

    generated = generate_viral_content(
        title=payload.title,
        duration=payload.duration,
        is_short=payload.is_short,
        transcript=subs,
        past_scripts=past_scripts
    )

    script_record = {
        "id": str(uuid.uuid4()),
        "video_id": video_id,
        "title": payload.title,
        "hook": f"1: {generated.get('hook_1')} | 2: {generated.get('hook_2')}",
        "body": generated.get("body"),
        "cta": generated.get("cta"),
        "prompt_thumb": generated.get("prompt_thumb")
    }
    db.save_script(script_record)
    # Auto mark video as scripted!
    db.update_video_status(video_id, "scripted")
    return generated

@app.get("/api/scripts")
async def get_all_scripts():
    return db.get_all_scripts()

# Video Downloader Endpoint
def remove_temp_file(path: str):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

@app.get("/api/videos/{video_id}/download")
async def download_video(video_id: str, quality: str = "720p", format_id: Optional[str] = None, background_tasks: BackgroundTasks = BackgroundTasks()):
    url = f"https://www.youtube.com/watch?v={video_id}"
    
    # Auto mark video as downloaded in DB
    db.batch_update_tags([video_id], "downloaded")

    temp_dir = tempfile.gettempdir()
    temp_id = uuid.uuid4().hex[:8]
    output_template = os.path.join(temp_dir, f"xit_{temp_id}.%(ext)s")

    is_audio = quality == "audio"
    ext = "mp3" if is_audio else "mp4"
    final_file = os.path.join(temp_dir, f"xit_{temp_id}.{ext}")

    ydl_opts = {
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 30,
    }
    if FFMPEG_PATH:
        ydl_opts['ffmpeg_location'] = FFMPEG_PATH

    if is_audio:
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    else:
        ydl_opts['merge_output_format'] = 'mp4'
        if quality == '360p':
            ydl_opts['format'] = 'bestvideo[height<=360]+bestaudio/best[height<=360]/best'
        elif quality == '1080p':
            ydl_opts['format'] = 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best'
        else:
            ydl_opts['format'] = 'bestvideo[height<=720]+bestaudio/best[height<=720]/best'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        actual_file = None
        if os.path.exists(final_file) and os.path.getsize(final_file) > 1000:
            actual_file = final_file
        else:
            for f in os.listdir(temp_dir):
                if f.startswith(f"xit_{temp_id}") and os.path.getsize(os.path.join(temp_dir, f)) > 1000:
                    actual_file = os.path.join(temp_dir, f)
                    break

        if not actual_file or not os.path.exists(actual_file):
            raise HTTPException(status_code=500, detail="Não foi possível processar o download do vídeo.")

        raw_title = (info.get("title") if info else None) or "video"
        nfkd = unicodedata.normalize('NFKD', raw_title)
        ascii_title = nfkd.encode('ASCII', 'ignore').decode('ASCII')
        clean_title = "".join(c for c in ascii_title if c.isalnum() or c in (' ', '_', '-')).strip() or "video"
        download_filename = f"{clean_title}.{ext}"

        background_tasks.add_task(remove_temp_file, actual_file)

        media_type = "audio/mpeg" if is_audio else "video/mp4"

        return FileResponse(
            path=actual_file,
            filename=download_filename,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{download_filename}"',
                "Access-Control-Expose-Headers": "Content-Disposition"
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao baixar: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
