import os
import shutil
import tempfile
import uuid
from typing import Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import yt_dlp

from database import db
from youtube_service import (
    get_channel_info,
    fetch_videos_from_channel,
    get_real_video_formats,
    extract_subtitles_text
)
from ai_service import generate_viral_content

app = FastAPI(title="XIT Studio", version="1.0.0")

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
    return {"status": "ok", "app": "XIT Studio", "service": "alive"}

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
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

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
    
    # Auto-fetch first batch of videos
    videos = fetch_videos_from_channel(info["url"], info["id"], limit=40)
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
    
    videos = fetch_videos_from_channel(target["url"], channel_id, limit=60)
    if videos:
        db.save_videos(videos)
    return {"status": "synced", "count": len(videos)}

# API: Videos
@app.get("/api/channels/{channel_id}/videos")
async def get_channel_videos(channel_id: str, filter_type: str = "all", status: str = "all"):
    return db.get_videos(channel_id=channel_id, filter_type=filter_type, status=status)

@app.post("/api/videos/{video_id}/status")
async def update_status(video_id: str, payload: UpdateStatusRequest):
    if payload.status not in ["pending", "downloaded", "posted"]:
        raise HTTPException(status_code=400, detail="Status inválido")
    db.update_video_status(video_id, payload.status)
    return {"status": "updated", "new_status": payload.status}

@app.get("/api/videos/{video_id}/formats")
async def get_formats(video_id: str):
    return get_real_video_formats(video_id)

# API: Script Generation (with Anti-Repetition)
@app.post("/api/videos/{video_id}/generate-script")
async def generate_script(video_id: str, payload: GenerateScriptRequest):
    # Check if already generated
    cached = db.get_script_by_video(video_id)
    if cached:
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
    return generated

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
    temp_dir = tempfile.gettempdir()
    output_template = os.path.join(temp_dir, f"xit_{video_id}_{uuid.uuid4().hex[:6]}.%(ext)s")

    # Format selection for maximum iOS compatibility
    is_audio = quality == "audio"
    if is_audio:
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output_template,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True,
            'no_warnings': True
        }
    else:
        # Choose matching resolution and enforce mp4 for iOS Photos
        if format_id and "bestvideo" in format_id:
            fmt = format_id
        elif quality == "1080p":
            fmt = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best"
        elif quality == "720p":
            fmt = "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best"
        else:
            fmt = "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"

        ydl_opts = {
            'format': fmt,
            'outtmpl': output_template,
            'merge_output_format': 'mp4',
            'quiet': True,
            'no_warnings': True
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if is_audio:
                filename = os.path.splitext(filename)[0] + ".mp3"
            elif not filename.endswith(".mp4") and os.path.exists(os.path.splitext(filename)[0] + ".mp4"):
                filename = os.path.splitext(filename)[0] + ".mp4"

            if not os.path.exists(filename):
                raise HTTPException(status_code=500, detail="Erro ao processar download do vídeo.")

            # Mark as downloaded in DB
            db.update_video_status(video_id, "downloaded")

            clean_title = "".join(c for c in (info.get("title") or "video") if c.isalnum() or c in (' ', '_', '-')).strip()
            download_filename = f"{clean_title}.{'mp3' if is_audio else 'mp4'}"

            # Auto-delete after streaming
            background_tasks.add_task(remove_temp_file, filename)

            return FileResponse(
                path=filename,
                filename=download_filename,
                media_type="audio/mpeg" if is_audio else "video/mp4"
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao baixar: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
