"""Persistent series relationships. Native favorites/history remain their own owner."""
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

IDENTITY = re.compile(r"[0-9]{8,24}").fullmatch
ORIGINS = ("http://tauri.localhost", "tauri://localhost")


def identity(value):
    # Do not accept floats: 64-bit IDs must reach the browser as decimal strings.
    return str(value) if type(value) in (int, str) and IDENTITY(str(value)) else None


class LibraryRelations:
    def __init__(self, directory, provider, clock=time.time):
        self.path = Path(directory) / "library-relations.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.provider, self.clock = provider, clock
        self.guard = threading.RLock()
        self.request_token = secrets.token_hex(32)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS relations (series_id TEXT PRIMARY KEY, "
                       "album_id TEXT, season INTEGER, title TEXT NOT NULL, state TEXT NOT NULL, retry_at INTEGER NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS manual_groups (series_id TEXT PRIMARY KEY, group_id TEXT NOT NULL)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def snapshot(self):
        with self.guard, self.connect() as db:
            rows = db.execute("SELECT series_id,album_id,season,title,state,retry_at FROM relations").fetchall()
            manual = dict(db.execute("SELECT series_id,group_id FROM manual_groups").fetchall())
        return {"relations": [self.row(row) for row in rows], "manual": manual}

    @staticmethod
    def row(row):
        return dict(zip(("seriesId", "albumId", "season", "title", "state", "retryAt"), row))

    def resolve(self, ids):
        if not isinstance(ids, list) or not 1 <= len(ids) <= 100 or any(type(sid) is not str or not identity(sid) for sid in ids):
            raise ValueError("每次最多查询100个有效剧集 ID")
        ids = list(dict.fromkeys(ids))
        # Holding one bounded batch lock merges overlapping HTTP requests as well
        # as requests that survive a browser cancellation. No membership writes.
        with self.guard, self.connect() as db:
            now = int(self.clock())
            cached = {row[0]: self.row(row) for row in db.execute(
                "SELECT series_id,album_id,season,title,state,retry_at FROM relations WHERE series_id IN ("
                + ",".join("?" for _ in ids) + ")", ids)}
            todo = [sid for sid in ids if sid not in cached or cached[sid]["retryAt"] and cached[sid]["retryAt"] <= now]
            for start in range(0, len(todo), 20):
                batch = todo[start:start + 20]
                try:
                    result = self.provider.api("POST", "/novel/player/multi_video_detail/v1/",
                        body=self.provider._episodes_body(",".join(batch)), max_retries=1)
                    data = result.get("data")
                    if result.get("code") != 0 or not isinstance(data, dict):
                        raise ValueError("Unavailable detail")
                except Exception:
                    data = {}
                for sid in batch:
                    vd = (data.get(sid) or {}).get("video_data") or {}
                    actual = identity(vd.get("series_id_str")) or identity(vd.get("series_id"))
                    valid = actual == sid and isinstance(vd.get("series_title"), str) and bool(vd["series_title"])
                    album = identity(vd.get("related_album_id")) if valid else None
                    season = vd.get("season_index") if valid else None
                    if type(season) is not int or not 1 <= season <= 999:
                        season = None
                    row = (sid, album, season, vd["series_title"][:500] if valid else "",
                           "resolved" if valid and album else "ungrouped" if valid else "failed",
                           0 if album else now + (86400 if valid else 300))
                    db.execute("INSERT INTO relations VALUES (?,?,?,?,?,?) ON CONFLICT(series_id) DO UPDATE SET "
                        "album_id=excluded.album_id,season=excluded.season,title=excluded.title,"
                        "state=excluded.state,retry_at=excluded.retry_at", row)
                    cached[sid] = self.row(row)
            return {"relations": [cached[sid] for sid in ids]}

    def is_next_season(self, current_id, next_id):
        """Use already resolved relationships; never infer from a title or search."""
        if not identity(current_id) or not identity(next_id) or current_id == next_id:
            return False
        with self.connect() as db:
            rows = db.execute("SELECT series_id,album_id,season,state FROM relations WHERE series_id IN (?,?)",
                              (current_id, next_id)).fetchall()
            values = {row[0]: row[1:] for row in rows}
            current, target = values.get(current_id), values.get(next_id)
            if not current or not target or not current[0] or current[0] != target[0]:
                return False
            if current[2] != "resolved" or target[2] != "resolved" or type(current[1]) is not int or type(target[1]) is not int:
                return False
            if current[1] < 1 or target[1] != current[1] + 1:
                return False
            count = db.execute("SELECT count(*) FROM relations WHERE album_id=? AND season=? AND state='resolved'",
                               (target[0], target[1])).fetchone()[0]
            return count == 1

    def set_manual(self, sid, target):
        if type(sid) is not str or not identity(sid) or target is not None and (type(target) is not str or not identity(target) or target == sid):
            raise ValueError("请选择不同的有效剧集")
        with self.guard, self.connect() as db:
            if target is None:
                db.execute("DELETE FROM manual_groups WHERE series_id=?", (sid,))
            else:
                row = db.execute("SELECT album_id FROM relations WHERE series_id=?", (target,)).fetchone()
                override = db.execute("SELECT group_id FROM manual_groups WHERE series_id=?", (target,)).fetchone()
                group = override[0] if override else "album:" + row[0] if row and row[0] else "manual:" + target
                # Anchor both unknown entries. An existing group stays stable.
                if group.startswith("manual:") and not override:
                    db.execute("INSERT INTO manual_groups VALUES (?,?) ON CONFLICT(series_id) DO UPDATE SET group_id=excluded.group_id", (target, group))
                db.execute("INSERT INTO manual_groups VALUES (?,?) ON CONFLICT(series_id) DO UPDATE SET group_id=excluded.group_id", (sid, group))
        return self.snapshot()


def make_router(service):
    router = APIRouter(prefix="/desktop/library")

    def check(request: Request):
        if request.headers.get("origin") not in ORIGINS:
            raise HTTPException(403, "不允许的来源")
        if request.headers.get("x-desktop-library-client") != "1":
            raise HTTPException(401, "需要桌面片单上下文")
        if request.method != "GET" and not secrets.compare_digest(request.headers.get("x-desktop-library-token", ""), service.request_token):
            raise HTTPException(401, "片单会话已失效，请重试")

    @router.get("", dependencies=[Depends(check)])
    def snapshot():
        return {**service.snapshot(), "requestToken": service.request_token}

    @router.post("/relations", dependencies=[Depends(check)])
    def relations(value: dict):
        try:
            return service.resolve(value.get("seriesIds"))
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        except (sqlite3.Error, OSError):
            raise HTTPException(503, "归组信息暂时无法保存，收藏不受影响") from None

    @router.post("/manual", dependencies=[Depends(check)])
    def manual(value: dict):
        try:
            return service.set_manual(value.get("seriesId"), value.get("targetId"))
        except ValueError as error:
            raise HTTPException(400, str(error)) from None

    return router
