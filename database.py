import os
import sqlite3
import requests
import json
from typing import List, Dict, Any, Optional

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "xit_data.db")

class Database:
    def __init__(self):
        self.headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }
        self.supabase_active = True
        self._init_sqlite()
        self._test_supabase()

    def _init_sqlite(self):
        conn = sqlite3.connect(SQLITE_DB_PATH)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS channels (
                id TEXT PRIMARY KEY,
                name TEXT,
                handle TEXT,
                avatar TEXT,
                url TEXT,
                notes TEXT DEFAULT '',
                is_favorite INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # Migrate existing schema if needed
        try:
            c.execute("ALTER TABLE channels ADD COLUMN notes TEXT DEFAULT ''")
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE channels ADD COLUMN is_favorite INTEGER DEFAULT 0")
        except Exception:
            pass

        c.execute('''
            CREATE TABLE IF NOT EXISTS videos (
                id TEXT PRIMARY KEY,
                channel_id TEXT,
                title TEXT,
                duration INTEGER,
                thumbnail TEXT,
                is_short INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                tags TEXT DEFAULT 'pending',
                url TEXT,
                published_at TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        try:
            c.execute("ALTER TABLE videos ADD COLUMN tags TEXT DEFAULT 'pending'")
        except Exception:
            pass
        c.execute('''
            CREATE TABLE IF NOT EXISTS scripts (
                id TEXT PRIMARY KEY,
                video_id TEXT,
                title TEXT,
                hook TEXT,
                body TEXT,
                cta TEXT,
                prompt_thumb TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()

    def _test_supabase(self):
        try:
            r = requests.get(f"{SUPABASE_URL}/rest/v1/channels?limit=1", headers=self.headers, timeout=4)
            if r.status_code == 200:
                self.supabase_active = True
            else:
                self.supabase_active = False
        except Exception:
            self.supabase_active = False

    # Channels
    def get_channels(self) -> List[Dict[str, Any]]:
        if self.supabase_active:
            try:
                r = requests.get(f"{SUPABASE_URL}/rest/v1/channels?select=*&order=is_favorite.desc,created_at.desc", headers=self.headers, timeout=5)
                if r.status_code == 200:
                    return r.json()
            except Exception:
                pass
        
        # Fallback SQLite
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM channels ORDER BY is_favorite DESC, created_at DESC")
        rows = [dict(row) for row in c.fetchall()]
        conn.close()
        return rows

    def save_channel(self, channel: Dict[str, Any]):
        # Save in Supabase
        if self.supabase_active:
            try:
                requests.post(f"{SUPABASE_URL}/rest/v1/channels", headers=self.headers, json=channel, timeout=5)
            except Exception:
                pass

        # Save in SQLite
        conn = sqlite3.connect(SQLITE_DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT OR REPLACE INTO channels (id, name, handle, avatar, url, notes, is_favorite)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (channel["id"], channel.get("name"), channel.get("handle"), channel.get("avatar"), channel.get("url"), channel.get("notes", ""), channel.get("is_favorite", 0)))
        conn.commit()
        conn.close()

    def update_channel_notes(self, channel_id: str, notes: str):
        if self.supabase_active:
            try:
                requests.patch(f"{SUPABASE_URL}/rest/v1/channels?id=eq.{channel_id}", headers=self.headers, json={"notes": notes}, timeout=5)
            except Exception:
                pass
        conn = sqlite3.connect(SQLITE_DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE channels SET notes = ? WHERE id = ?", (notes, channel_id))
        conn.commit()
        conn.close()

    def toggle_channel_favorite(self, channel_id: str) -> int:
        conn = sqlite3.connect(SQLITE_DB_PATH)
        c = conn.cursor()
        c.execute("SELECT is_favorite FROM channels WHERE id = ?", (channel_id,))
        row = c.fetchone()
        current = row[0] if row else 0
        new_val = 0 if current == 1 else 1
        c.execute("UPDATE channels SET is_favorite = ? WHERE id = ?", (new_val, channel_id))
        conn.commit()
        conn.close()

        if self.supabase_active:
            try:
                requests.patch(f"{SUPABASE_URL}/rest/v1/channels?id=eq.{channel_id}", headers=self.headers, json={"is_favorite": new_val}, timeout=5)
            except Exception:
                pass
        return new_val

    def delete_channel(self, channel_id: str):
        if self.supabase_active:
            try:
                requests.delete(f"{SUPABASE_URL}/rest/v1/channels?id=eq.{channel_id}", headers=self.headers, timeout=5)
                requests.delete(f"{SUPABASE_URL}/rest/v1/videos?channel_id=eq.{channel_id}", headers=self.headers, timeout=5)
            except Exception:
                pass

        conn = sqlite3.connect(SQLITE_DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
        c.execute("DELETE FROM videos WHERE channel_id = ?", (channel_id,))
        conn.commit()
        conn.close()

    # Videos
    def get_videos(self, channel_id: Optional[str] = None, filter_type: str = "all", status: str = "all", sort_order: str = "asc") -> List[Dict[str, Any]]:
        order_direction = "asc" if sort_order == "asc" else "desc"

        # SQLite
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        sql = "SELECT * FROM videos WHERE 1=1"
        params = []
        if channel_id:
            sql += " AND channel_id = ?"
            params.append(channel_id)
        if filter_type == "video":
            sql += " AND is_short = 0"
        elif filter_type == "short":
            sql += " AND is_short = 1"
        if status != "all":
            sql += " AND (tags LIKE ? OR status = ?)"
            params.append(f"%{status}%")
            params.append(status)
        sql += f" ORDER BY CASE WHEN published_at IS NOT NULL AND published_at != '' THEN published_at ELSE rowid END {order_direction.upper()}"
        c.execute(sql, params)
        raw_rows = [dict(row) for row in c.fetchall()]
        conn.close()

        # Parse tags as clean array
        for r in raw_rows:
            raw_tags = r.get("tags") or r.get("status") or "pending"
            tag_list = [t.strip() for t in str(raw_tags).split(",") if t.strip()]
            r["tags"] = tag_list if tag_list else ["pending"]

        return raw_rows

    def save_videos(self, videos: List[Dict[str, Any]]):
        if not videos:
            return

        conn = sqlite3.connect(SQLITE_DB_PATH)
        c = conn.cursor()
        for v in videos:
            tags_val = v.get("tags")
            if isinstance(tags_val, list):
                tags_str = ",".join(tags_val)
            else:
                tags_str = tags_val or v.get("status") or "pending"

            c.execute('''
                INSERT OR REPLACE INTO videos (id, channel_id, title, duration, thumbnail, is_short, status, tags, url, published_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                v["id"], v.get("channel_id"), v.get("title"), v.get("duration", 0),
                v.get("thumbnail"), 1 if v.get("is_short") else 0,
                v.get("status", "pending"), tags_str, v.get("url"), v.get("published_at")
            ))
        conn.commit()
        conn.close()

    def delete_video(self, video_id: str):
        conn = sqlite3.connect(SQLITE_DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM videos WHERE id = ?", (video_id,))
        c.execute("DELETE FROM scripts WHERE video_id = ?", (video_id,))
        conn.commit()
        conn.close()

    def delete_videos(self, video_ids: List[str]):
        if not video_ids:
            return
        conn = sqlite3.connect(SQLITE_DB_PATH)
        c = conn.cursor()
        placeholders = ",".join("?" for _ in video_ids)
        c.execute(f"DELETE FROM videos WHERE id IN ({placeholders})", tuple(video_ids))
        c.execute(f"DELETE FROM scripts WHERE video_id IN ({placeholders})", tuple(video_ids))
        conn.commit()
        conn.close()

    def update_video_tags(self, video_id: str, tags: List[str]):
        tags_str = ",".join(tags) if tags else "pending"
        primary_status = tags[0] if tags else "pending"
        conn = sqlite3.connect(SQLITE_DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE videos SET tags = ?, status = ? WHERE id = ?", (tags_str, primary_status, video_id))
        conn.commit()
        conn.close()

    def batch_update_tags(self, video_ids: List[str], tag_to_add: str):
        if not video_ids:
            return
        conn = sqlite3.connect(SQLITE_DB_PATH)
        c = conn.cursor()
        for vid in video_ids:
            c.execute("SELECT tags FROM videos WHERE id = ?", (vid,))
            row = c.fetchone()
            current = [t.strip() for t in (row[0] or "pending").split(",") if t.strip()] if row else []
            if tag_to_add not in current:
                current.append(tag_to_add)
            tags_str = ",".join(current)
            c.execute("UPDATE videos SET tags = ?, status = ? WHERE id = ?", (tags_str, tag_to_add, vid))
        conn.commit()
        conn.close()

    def update_video_status(self, video_id: str, status: str):
        self.update_video_tags(video_id, [status])

    # Scripts & Anti-Repetition
    def get_past_script_titles(self, limit: int = 15) -> List[str]:
        if self.supabase_active:
            try:
                r = requests.get(f"{SUPABASE_URL}/rest/v1/scripts?select=title,hook&order=created_at.desc&limit={limit}", headers=self.headers, timeout=5)
                if r.status_code == 200:
                    return [f"{s.get('title', '')} ({s.get('hook', '')[:60]}...)" for s in r.json()]
            except Exception:
                pass

        conn = sqlite3.connect(SQLITE_DB_PATH)
        c = conn.cursor()
        c.execute("SELECT title, hook FROM scripts ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = [f"{row[0]} ({row[1][:60] if row[1] else ''}...)" for row in c.fetchall()]
        conn.close()
        return rows

    def save_script(self, script: Dict[str, Any]):
        if self.supabase_active:
            try:
                headers = dict(self.headers)
                headers["Prefer"] = "resolution=merge-duplicates"
                requests.post(f"{SUPABASE_URL}/rest/v1/scripts", headers=headers, json=script, timeout=5)
            except Exception:
                pass

        conn = sqlite3.connect(SQLITE_DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT OR REPLACE INTO scripts (id, video_id, title, hook, body, cta, prompt_thumb)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            script["id"], script.get("video_id"), script.get("title"),
            script.get("hook"), script.get("body"), script.get("cta"),
            script.get("prompt_thumb")
        ))
        conn.commit()
        conn.close()

    def get_script_by_video(self, video_id: str) -> Optional[Dict[str, Any]]:
        if self.supabase_active:
            try:
                r = requests.get(f"{SUPABASE_URL}/rest/v1/scripts?video_id=eq.{video_id}&limit=1", headers=self.headers, timeout=5)
                if r.status_code == 200 and r.json():
                    return r.json()[0]
            except Exception:
                pass

        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM scripts WHERE video_id = ? ORDER BY created_at DESC LIMIT 1", (video_id,))
        row = c.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_all_scripts(self, limit: int = 50) -> List[Dict[str, Any]]:
        if self.supabase_active:
            try:
                r = requests.get(f"{SUPABASE_URL}/rest/v1/scripts?select=*&order=created_at.desc&limit={limit}", headers=self.headers, timeout=5)
                if r.status_code == 200:
                    return r.json()
            except Exception:
                pass

        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM scripts ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = [dict(row) for row in c.fetchall()]
        conn.close()
        return rows

db = Database()
