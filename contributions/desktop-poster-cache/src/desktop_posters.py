"""Shared persistent poster bytes, compatible with the native .cover cache."""
import base64
import io
import os
from pathlib import Path
import re
import stat
import tempfile
import threading
import time
from urllib.parse import urlsplit

from PIL import Image

MAX_BYTES = 2 * 1024 * 1024
IMAGE_HOSTS = ("fqnovelpic.com", "byteimg.com", "qznovelvod.com", "douyinpic.com", "pstatp.com")


def cover_url(value):
    if not isinstance(value, str) or len(value) > 8192:
        return None
    try:
        url = urlsplit(value)
        host = (url.hostname or "").lower()
        if url.scheme in ("http", "https") and not url.username and not url.password and any(
                host == domain or host.endswith("." + domain) for domain in IMAGE_HOSTS):
            return value
    except ValueError:
        pass
    return None


class PosterCache:
    def __init__(self, directory, fetch, clock=time.time):
        # Resolve the user-selected directory mapping once; individual linked
        # files are still rejected. Native and backend consume the same bytes.
        root = Path(directory) / "poster-cache-v1"
        root.mkdir(parents=True, exist_ok=True)
        self.root = root.resolve(strict=True)
        self.fetch, self.clock = fetch, clock
        self.guard = threading.Lock()
        self.locks, self.failed_until = {}, {}
        self._next = None

    def path(self, sid):
        if type(sid) is not str or not re.fullmatch(r"[0-9]{8,24}", sid):
            raise ValueError("无效的封面剧集 ID")
        return self.root / (sid + ".cover")

    @staticmethod
    def encode(data):
        if not isinstance(data, bytes) or not 0 < len(data) <= MAX_BYTES:
            raise ValueError("封面超过大小限制")
        with Image.open(io.BytesIO(data)) as image:
            kind = {"JPEG": "jpeg", "PNG": "png", "WEBP": "webp"}.get(image.format)
            if not kind or image.width * image.height > 16000000:
                raise ValueError("封面不是支持的图片")
            image.verify()
        return "data:image/" + kind + ";base64," + base64.b64encode(data).decode("ascii")

    def read(self, sid):
        if self._next is not None:
            return self._next.read(sid)
        path = self.path(sid)
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400 or not 0 < info.st_size <= MAX_BYTES:
                return None
            with path.open("rb") as source:
                return self.encode(source.read(MAX_BYTES + 1))
        except (OSError, ValueError, SyntaxError):
            return None

    def ready_to_fetch(self, sid):
        self.path(sid)
        with self.guard:
            return self.failed_until.get(sid, 0) <= self.clock()

    def failed(self, sid):
        with self.guard:
            self.failed_until[sid] = self.clock() + 300

    def _publish(self, sid, data):
        if self._next is not None:
            return self._next._publish(sid, data)
        encoded = self.encode(data)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, prefix=sid + ".", suffix=".tmp", delete=False) as target:
                temporary = Path(target.name)
                target.write(data)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, self.path(sid))
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        # A settings commit may happen while this atomic write is in flight.
        if self._next is not None:
            return self._next._publish(sid, data)
        return encoded

    def seed_from(self, previous):
        if self.root == previous.root:
            return
        for path in previous.root.iterdir():
            match = re.fullmatch(r"([0-9]{8,24})\.cover", path.name)
            if match and not self.read(match[1]):
                encoded = previous.read(match[1])
                if encoded:
                    self._publish(match[1], base64.b64decode(encoded.split(",", 1)[1]))

    def prepare_directory(self, directory):
        candidate = PosterCache(directory, self.fetch, self.clock)
        candidate.seed_from(self)
        # Share identity locks and cooldowns with downloads already in flight.
        candidate.guard, candidate.locks, candidate.failed_until = self.guard, self.locks, self.failed_until
        return candidate

    def activate(self, candidate):
        if candidate is not self:
            self._next = candidate

    def get(self, sid, url):
        cached = self.read(sid)
        if cached:
            return cached
        with self.guard:
            lock = self.locks.setdefault(sid, threading.Lock())
        with lock:
            cached = self.read(sid)
            if cached:
                return cached
            if not self.ready_to_fetch(sid):
                return None
            if not cover_url(url):
                self.failed(sid)
                return None
            try:
                encoded = self._publish(sid, self.fetch(url))
                with self.guard:
                    self.failed_until.pop(sid, None)
                return encoded
            except Exception:
                self.failed(sid)
                return None
