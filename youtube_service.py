import os
import re
import yt_dlp
from typing import List, Dict, Any, Optional

def clean_channel_url(input_str: str) -> str:
    input_str = input_str.strip()
    if input_str.startswith("@"):
        return f"https://www.youtube.com/{input_str}"
    if not input_str.startswith("http"):
        if input_str.startswith("UC"):
            return f"https://www.youtube.com/channel/{input_str}"
        return f"https://www.youtube.com/@{input_str}"
    return input_str

def get_channel_info(channel_input: str) -> Optional[Dict[str, Any]]:
    input_str = channel_input.strip()
    
    # Check if user entered a video URL or shorts URL
    if "watch?v=" in input_str or "youtu.be/" in input_str or "/shorts/" in input_str:
        ydl_opts = {'quiet': True, 'skip_download': True, 'no_warnings': True}
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(input_str, download=False)
                ch_id = info.get('channel_id')
                ch_name = info.get('uploader') or info.get('channel') or "Canal YouTube"
                ch_url = info.get('channel_url') or f"https://www.youtube.com/channel/{ch_id}"
                avatar = f"https://api.dicebear.com/7.x/identicon/svg?seed={ch_id}"
                return {
                    "id": str(ch_id),
                    "name": ch_name,
                    "handle": ch_name,
                    "avatar": avatar,
                    "url": ch_url
                }
        except Exception as e:
            print(f"Error extracting from video url: {e}")

    # Standard Channel extraction
    url = clean_channel_url(input_str)
    ydl_opts = {
        'extract_flat': True,
        'playlistend': 1,
        'quiet': True,
        'no_warnings': True
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            if not info:
                return None
            
            channel_id = info.get('channel_id') or info.get('id') or re.sub(r'[^a-zA-Z0-9_-]', '', url.split('/')[-1])
            channel_name = info.get('channel') or info.get('uploader') or info.get('title') or "Canal YouTube"
            
            if channel_name.endswith(" - Videos"):
                channel_name = channel_name[:-9]

            thumbnails = info.get('thumbnails', [])
            avatar = thumbnails[-1]['url'] if thumbnails else f"https://api.dicebear.com/7.x/identicon/svg?seed={channel_id}"

            return {
                "id": str(channel_id),
                "name": channel_name,
                "handle": url.split('/')[-1],
                "avatar": avatar,
                "url": url
            }
        except Exception as e:
            print(f"Error fetching channel info: {e}")
            return None

def fetch_videos_from_channel(channel_url: str, channel_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    clean_url = clean_channel_url(channel_url)
    videos = []
    seen_ids = set()

    ydl_opts = {
        'extract_flat': True,
        'playlistend': limit,
        'quiet': True,
        'no_warnings': True
    }

    # 1. Primary Method: Fetch directly from /videos tab and /shorts tab for 100% faithful categorization
    tabs = [
        (f"{clean_url}/videos", False),
        (f"{clean_url}/shorts", True)
    ]
    for target_url, force_short in tabs:
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(target_url, download=False)
                entries = info.get('entries', []) or []
                total_entries = len(entries)
                for idx, entry in enumerate(entries):
                    if not entry:
                        continue
                    v_id = entry.get('id')
                    if not v_id or v_id in seen_ids:
                        continue
                    seen_ids.add(v_id)

                    duration = entry.get('duration') or 0
                    thumbs = entry.get('thumbnails', [])
                    thumb_url = thumbs[-1]['url'] if thumbs else f"https://i.ytimg.com/vi/{v_id}/hqdefault.jpg"

                    # Synthetic sort rank if upload_date is None (YouTube gives newest first in tabs)
                    # Higher number = newer upload
                    synth_rank = total_entries - idx
                    pub_date = entry.get('upload_date') or f"idx_{synth_rank:04d}"

                    videos.append({
                        "id": v_id,
                        "channel_id": channel_id,
                        "title": entry.get('title') or "Sem título",
                        "duration": int(duration),
                        "thumbnail": thumb_url,
                        "is_short": force_short,
                        "status": "pending",
                        "tags": "pending",
                        "url": f"https://www.youtube.com/watch?v={v_id}",
                        "published_at": pub_date
                    })
        except Exception as e:
            print(f"Error fetching {target_url}: {e}")

    # 2. Fallback if tabs returned nothing (legacy channel or direct playlist)
    if len(videos) == 0 and channel_id and channel_id.startswith("UC"):
        uploads_playlist_url = f"https://www.youtube.com/playlist?list=UU{channel_id[2:]}"
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(uploads_playlist_url, download=False)
                entries = info.get('entries', []) or []
                total_entries = len(entries)
                for idx, entry in enumerate(entries):
                    if not entry:
                        continue
                    v_id = entry.get('id')
                    if not v_id or v_id in seen_ids:
                        continue
                    seen_ids.add(v_id)

                    duration = entry.get('duration') or 0
                    is_short = "/shorts/" in entry.get('url', '')
                    thumbs = entry.get('thumbnails', [])
                    thumb_url = thumbs[-1]['url'] if thumbs else f"https://i.ytimg.com/vi/{v_id}/hqdefault.jpg"
                    synth_rank = total_entries - idx
                    pub_date = entry.get('upload_date') or f"idx_{synth_rank:04d}"

                    videos.append({
                        "id": v_id,
                        "channel_id": channel_id,
                        "title": entry.get('title') or "Sem título",
                        "duration": int(duration),
                        "thumbnail": thumb_url,
                        "is_short": is_short,
                        "status": "pending",
                        "tags": "pending",
                        "url": f"https://www.youtube.com/watch?v={v_id}",
                        "published_at": pub_date
                    })
        except Exception as e:
            print(f"Uploads playlist extraction error: {e}")

    return videos

def get_real_video_formats(video_id: str) -> List[Dict[str, Any]]:
    url = f"https://www.youtube.com/watch?v={video_id}"
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extractor_args': {'youtube': {'player_client': ['android_vr', 'web']}}
    }
    formats_list = []
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            formats = info.get('formats', [])
            
            height_map = {}
            audio_format = None

            for f in formats:
                h = f.get('height')
                ext = f.get('ext')
                vcodec = f.get('vcodec')
                acodec = f.get('acodec')

                if vcodec == 'none' and acodec != 'none':
                    audio_format = f

                if h and h in [1080, 720, 480, 360]:
                    if h not in height_map or (ext == 'mp4' and height_map[h].get('ext') != 'mp4'):
                        height_map[h] = f

            for h in sorted(height_map.keys(), reverse=True):
                f = height_map[h]
                size_bytes = f.get('filesize') or f.get('filesize_approx') or 0
                size_mb = f"{round(size_bytes / (1024 * 1024), 1)} MB" if size_bytes else "Qualidade Original"
                
                formats_list.append({
                    "quality": f"{h}p",
                    "format_id": f.get('format_id'),
                    "ext": "mp4",
                    "label": f"{h}p {'Full HD' if h==1080 else 'HD' if h==720 else 'SD'}",
                    "size": size_mb
                })

            if audio_format:
                a_size = audio_format.get('filesize') or audio_format.get('filesize_approx') or 0
                formats_list.append({
                    "quality": "audio",
                    "format_id": audio_format.get('format_id'),
                    "ext": "mp3",
                    "label": "Apenas Áudio (MP3)",
                    "size": f"{round(a_size / (1024 * 1024), 1)} MB" if a_size else "Áudio puro"
                })

        except Exception as e:
            print(f"Error extracting formats: {e}")

    if not formats_list:
        formats_list = [
            {"quality": "1080p", "format_id": "bestvideo[height<=1080]+bestaudio/best[height<=1080]", "ext": "mp4", "label": "1080p Full HD", "size": "Fiel ao YouTube"},
            {"quality": "720p", "format_id": "bestvideo[height<=720]+bestaudio/best[height<=720]", "ext": "mp4", "label": "720p HD", "size": "Fiel ao YouTube"},
            {"quality": "480p", "format_id": "bestvideo[height<=480]+bestaudio/best[height<=480]", "ext": "mp4", "label": "480p SD", "size": "Fiel ao YouTube"},
            {"quality": "audio", "format_id": "bestaudio/best", "ext": "mp3", "label": "Apenas Áudio (MP3)", "size": "Áudio puro"}
        ]

    return formats_list

def extract_subtitles_text(video_id: str) -> str:
    url = f"https://www.youtube.com/watch?v={video_id}"
    ydl_opts = {
        'skip_download': True,
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': ['pt', 'en'],
        'quiet': True,
        'no_warnings': True
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            return ""
        except Exception:
            return ""
