"""Desktop video cache settings, persisted independently of account data."""
import json
import os
from pathlib import Path
import subprocess
import secrets
import tempfile
import threading
import re
import shutil
import time

from fastapi import APIRouter, Depends, HTTPException, Request


def validate_ahead(value):
    if value == "all":
        return None
    if type(value) is not int or not 1 <= value <= 100000:
        raise ValueError("缓存集数须为1至100000的整数，或全部")
    return value


def validate_limit(value):
    if type(value) is not int or not 1 <= value <= 100000:
        raise ValueError("缓存上限须为正整数GB")
    return value


def writable_directory(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError("请选择有效的缓存目录")
    path = Path(value.strip())
    if not path.is_absolute():
        raise ValueError("缓存目录须为绝对路径")
    path.mkdir(parents=True, exist_ok=True)
    path = path.resolve(strict=True)
    with tempfile.TemporaryFile(prefix=".hongguo-write-", dir=path) as probe:
        probe.write(b"cache-settings-v1")
        probe.flush()
    return path


def video_cache_directory(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError("请选择有效的缓存目录")
    path = Path(value.strip())
    if not path.is_absolute():
        raise ValueError("缓存目录须为绝对路径")
    return path if path.name.casefold() == 'video-cache' else path / 'video-cache'


def default_application_cache_root():
    # Explicit isolated profiles are for testing; the normal product default
    # comes from Windows application data, never from the selected cache setting.
    if os.environ.get('HONGGUO_DATA_DIR'):
        return Path(os.environ['HONGGUO_DATA_DIR'])
    return Path(os.environ['APPDATA']) / 'cn.guoban.desktop-companion'


class CacheSettings:
    def __init__(self, data, default_root):
        self.path = Path(data) / "video-cache-settings.json"
        self.default_root = video_cache_directory(str(default_root))
        self.guard = threading.Lock()
        self.picker_guard = threading.Lock()
        self.request_token = secrets.token_hex(32)
        self.prepare_change = None
        self.clear_cache = None
        self.active_root = self.load()["directory"]

    def load(self):
        for attempt in range(3):
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
                break
            except FileNotFoundError:
                return {"directory": str(self.default_root), "ahead": 3, "custom": False, "limitGB": 10}
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(.02)  # Windows scanners can briefly lock an atomic replacement.
        if not isinstance(value, dict) or set(value) not in ({"directory", "ahead", "custom"}, {"directory", "ahead", "custom", "limitGB"}):
            raise ValueError("缓存设置文件无效")
        validate_ahead(value["ahead"])
        value.setdefault("limitGB", 10)
        validate_limit(value["limitGB"])
        if not isinstance(value["directory"], str) or not Path(value["directory"]).is_absolute() or type(value["custom"]) is not bool:
            raise ValueError("缓存目录设置无效")
        value['directory'] = str(video_cache_directory(value['directory']))
        return value

    def snapshot(self):
        value = self.load()
        return {**value, "defaultDirectory": str(self.default_root), "activeDirectory": self.active_root,
                "restartRequired": os.path.normcase(value["directory"]) != os.path.normcase(self.active_root)}

    def save(self, value):
        if not isinstance(value, dict) or set(value) not in ({"directory", "ahead"}, {"directory", "ahead", "limitGB"}):
            raise ValueError("缓存设置字段无效")
        validate_ahead(value["ahead"])
        limit = validate_limit(value.get("limitGB", 10))
        directory = writable_directory(str(video_cache_directory(value["directory"])))
        result = {"directory": str(directory), "ahead": value["ahead"], "custom": True, "limitGB": limit}
        with self.guard:
            apply_change = self.prepare_change(result) if self.prepare_change else None
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".video-cache-settings-", dir=self.path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
                    json.dump(result, output, ensure_ascii=False)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, self.path)
                if apply_change:
                    apply_change()
                    self.active_root = result["directory"]
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return self.snapshot()

    def startup_paths(self, work, value=None):
        value = self.load() if value is None else value
        root = writable_directory(value["directory"])
        streams = writable_directory(str(root / "stream-cache"))
        sessions = writable_directory(str(root / "playback-sessions"))
        self._reap_sessions(sessions)
        work = Path(tempfile.mkdtemp(prefix="session-", dir=sessions))
        (work / "owner.json").write_text(json.dumps({"owner":"hongguo-video-session-v1", "pid":os.getpid()}), encoding="utf-8")
        return streams, work, True

    @staticmethod
    def _process_alive(pid):
        if type(pid) is not int or pid <= 0:
            return True
        if os.name != "nt":
            try:
                os.kill(pid, 0)
                return True
            except ProcessLookupError:
                return False
            except OSError:
                return True
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if handle:
            kernel.CloseHandle(handle)
            return True
        return ctypes.get_last_error() != 87  # ERROR_INVALID_PARAMETER: PID absent.

    @classmethod
    def _reap_sessions(cls, sessions):
        # Kill-on-exit can bypass Python finally. Reclaim only marked, dead owners.
        for child in sessions.iterdir():
            try:
                if not re.fullmatch(r"session-[a-z0-9_]{8}", child.name) or child.is_symlink() or child.resolve().parent != sessions:
                    continue
                marker = child / "owner.json"
                if marker.is_symlink():
                    continue
                value = json.loads(marker.read_text(encoding="utf-8"))
                if value.get("owner") == "hongguo-video-session-v1" and not cls._process_alive(value.get("pid")):
                    shutil.rmtree(child)
            except (OSError, ValueError, AttributeError):
                pass  # Unknown or inaccessible files are preserved.

    def choose(self):
        if not self.picker_guard.acquire(blocking=False):
            raise ValueError("目录选择窗口已打开")
        try:
            script = """$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Windows.Forms
$dialog=[System.Windows.Forms.FolderBrowserDialog]::new()
$dialog.Description='选择视频缓存目录'
$dialog.UseDescriptionForTitle=$true
$dialog.ShowNewFolderButton=$true
try { if($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { [Console]::Write($dialog.SelectedPath) } } finally { $dialog.Dispose() }
"""
            completed = subprocess.run(["pwsh.exe", "-NoProfile", "-STA", "-Command", script],
                                       capture_output=True, timeout=180,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if completed.returncode:
                raise OSError("Directory picker failed")
            return completed.stdout.decode("utf-8").strip() or None
        finally:
            self.picker_guard.release()


def make_router(settings, origins=("http://tauri.localhost", "tauri://localhost")):
    router = APIRouter(prefix="/desktop/cache-settings")

    def check(request: Request):
        if request.headers.get("origin") not in origins:
            raise HTTPException(403, "不允许的来源")
        if request.headers.get("x-desktop-cache-client") != "1":
            raise HTTPException(401, "需要桌面设置上下文")
        if request.method != "GET" and not secrets.compare_digest(request.headers.get("x-desktop-cache-token", ""), settings.request_token):
            raise HTTPException(401, "桌面设置会话已失效，请重新打开设置")

    @router.get("", dependencies=[Depends(check)])
    def get_settings():
        return {**settings.snapshot(), "requestToken": settings.request_token}

    @router.post("", dependencies=[Depends(check)])
    def save_settings(value: dict):
        try:
            return settings.save(value)
        except (ValueError, OSError):
            raise HTTPException(400, "保存失败，请检查目录和数值") from None

    @router.post("/choose", dependencies=[Depends(check)])
    def choose_directory():
        try:
            return {"directory": settings.choose()}
        except (ValueError, OSError, subprocess.TimeoutExpired):
            raise HTTPException(409, "未能选择目录，请重试或手动输入完整路径") from None

    @router.post("/clear", dependencies=[Depends(check)])
    def clear_cache():
        if not settings.clear_cache:
            raise HTTPException(503, "清理缓存暂不可用")
        try:
            with settings.guard:
                return settings.clear_cache()
        except OSError:
            raise HTTPException(409, "部分缓存正在使用，请稍后重试") from None

    return router


def clean_video_cache(root, cache, *, protected=(), busy=False, extra_bytes=0):
    """Delete only recognized originals and fully owned HLS entries, oldest first."""
    from desktop_playable_cache import plain
    root = Path(root).resolve(strict=True)
    protected = {Path(path).resolve() for path in protected if path is not None}
    hls_file = re.compile(r"(?:owner\.marker|cache\.json|complete\.marker|index\.m3u8|init\.mp4|seg[0-9]{6}\.m4s)").fullmatch
    candidates = []
    total = extra_bytes
    for path in root.iterdir():
        if not path.is_file() or not plain(path):
            continue
        info = path.stat(); total += info.st_size
        if re.fullmatch(r"[0-9]{8,24}_[A-Za-z0-9]+(?:\.raw)?\.mp4", path.name) and path.resolve() not in protected:
            candidates.append((info.st_mtime, path, info.st_size, False))
    if cache.available:
        for entry in cache.root.iterdir():
            if not entry.is_dir() or not plain(entry):
                continue
            try:
                children = cache._owned_children(entry)
                size = sum(path.stat().st_size for path in children);total += size
                known = all(hls_file(path.name) for path in children)
                if not busy and known:
                    candidates.append((entry.stat().st_mtime, entry, size, True))
            except (ValueError, OSError, UnicodeError):
                continue
    removed = []; freed = 0
    for _, path, size, hls in sorted(candidates, key=lambda item:item[0]):
        try:
            if hls:
                with cache.guard:
                    if any(not hls_file(child.name) for child in cache._owned_children(path)):
                        continue
                    cache._remove_owned(path)
            elif path.parent == root and plain(path) and path.resolve() not in protected:
                path.unlink()
            else:
                continue
            total -= size;freed += size;removed.append(path)
        except (OSError, ValueError):
            continue
    return {"clearedBytes":freed, "clearedFiles":len(removed), "remainingBytes":max(0,total), "removed":removed}
