"""Bounded HTTP Range input shared by PyAV and libmpv; CENC stays in FFmpeg.

Provider URLs and keys remain private Python state. Neither the browser nor a
command line receives them. The block cache is bounded and dies with the source.
"""
from collections import OrderedDict
from contextlib import contextmanager
import hashlib
import io
import re
import threading
import time
import tempfile
from email.utils import parsedate_to_datetime

import requests
from urllib.parse import urlsplit


class SourceReadError(OSError):
    pass


class ProgressiveSource:
    block_size = 65536
    max_blocks = 256  # 16 MiB per active source; no persistent partial files.

    def __init__(self, url, *, request, identity, key=None, size=0):
        parts = urlsplit(url)
        if (parts.scheme not in ("http", "https") or not parts.hostname
                or parts.username or parts.password or parts.fragment):
            raise ValueError("Invalid provider media endpoint")
        if key is not None and not re.fullmatch(r"[0-9a-fA-F]{32}", key):
            raise ValueError("Invalid media encryption configuration")
        self._url, self._request, self._key = url, request, key
        self.identity = str(identity)
        self.path_hash = hashlib.sha256((parts.netloc + parts.path).encode()).hexdigest()
        self.size = int(size or 0)
        if not 0 <= self.size <= 2 * 1024 ** 3:
            raise ValueError("Media input budget exceeded")
        self.guard = threading.RLock()
        self.fetch_guard = threading.Lock()
        self.blocks = OrderedDict()
        self.seen = set()
        self.received = 0
        self.validator = None
        self.if_range = None
        self.pinned = None
        self.closed = threading.Event()
        self.network_failed = threading.Event()
        self.reading = threading.Event()

    def __repr__(self):
        return "<ProgressiveSource>"

    def options(self):
        return {"decryption_key": self._key} if self._key else {}

    def cache_identity(self):
        return {"kind": "http-range-v1", "id": self.identity,
                "object": self.path_hash, "size": self.size, "validator": self.validator}

    def snapshot(self):
        with self.guard:
            return {"kind": "progressive", "receivedBytes": self.received,
                    "totalBytes": self.size, "complete": bool(not self.closed.is_set() and self.size and self.received == self.size),
                    "cachedBytes": sum(len(v) for v in self.blocks.values())}

    def block(self, index, cancelled):
        caller_cancelled = cancelled
        cancelled = lambda: self.closed.is_set() or caller_cancelled()
        with self.fetch_guard:
            if self.closed.is_set():
                raise SourceReadError("Media input is closed")
            if cancelled():
                raise InterruptedError("Media read cancelled")
            with self.guard:
                if index in self.blocks:
                    self.blocks.move_to_end(index)
                    return self.blocks[index]
            start = index * self.block_size
            if self.size and start >= self.size:
                return b""
            if self.pinned is not None:
                self.pinned.seek(start)
                return self.pinned.read(self.block_size)
            end = start + self.block_size - 1
            headers = {"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"}
            if self.if_range:
                headers["If-Range"] = self.if_range
            try:
                self.reading.set()
                for attempt in range(3):
                    if cancelled():
                        raise InterruptedError("Media read cancelled")
                    try:
                        value, total, validator = self._range(start, end, headers, cancelled)
                        break
                    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError,
                            requests.exceptions.ChunkedEncodingError):
                        if cancelled():
                            raise InterruptedError("Media read cancelled")
                        if attempt == 2:
                            raise
                        # Keep the player in its cache/buffering path. Do not
                        # poison the source for a recoverable transport stall.
                        until = time.monotonic() + .25
                        while time.monotonic() < until:
                            if cancelled():
                                raise InterruptedError("Media read cancelled")
                            time.sleep(.025)
                if cancelled():
                    raise InterruptedError("Media read cancelled")
                with self.guard:
                    self.size, self.validator = total, validator
                    self.blocks[index] = value
                    if self.pinned is None and index not in self.seen:
                        self.seen.add(index)
                        self.received += len(value)
                    while len(self.blocks) > self.max_blocks:
                        self.blocks.popitem(last=False)
                return value
            except InterruptedError:
                raise
            except Exception:
                self.network_failed.set()
                raise SourceReadError("Media range read failed") from None
            finally:
                self.reading.clear()

    def _range(self, start, end, headers, cancelled):
        response = None
        try:
            response = self._request("GET", self._url, headers=headers,
                                     stream=True, timeout=(3, 10))
            match = re.fullmatch(r"bytes ([0-9]+)-([0-9]+)/([0-9]+)",
                                 response.headers.get("Content-Range", ""))
            if response.status_code != 206 or not match:
                raise SourceReadError("Provider does not support byte ranges")
            first, last, total = map(int, match.groups())
            if (first != start or last != min(end, total - 1)
                    or not 0 < total <= 2 * 1024 ** 3 or self.size and self.size != total):
                raise SourceReadError("Invalid provider byte range")
            etag = response.headers.get("ETag")
            validator = etag if etag and re.fullmatch(r'"[\x21\x23-\x7e\x80-\xff]*"', etag) else None
            if not etag:
                modified = response.headers.get("Last-Modified")
                try:
                    if modified and parsedate_to_datetime(modified).tzinfo is not None:
                        validator = modified
                except (ValueError, TypeError, OverflowError):
                    pass
            if self.validator and validator != self.validator:
                raise SourceReadError("Provider media changed")
            if not validator:
                # Length alone cannot identify a representation. Discard the
                # unversioned range and pin a single complete HTTP response.
                response.close();response=None
                self._pin(total,cancelled)
                self.pinned.seek(start)
                return self.pinned.read(last-first+1),total,self.validator
            data = bytearray()
            for chunk in response.iter_content(16384):
                if cancelled():
                    raise InterruptedError("Media read cancelled")
                data.extend(chunk)
                if len(data) > last - first + 1:
                    raise SourceReadError("Provider range exceeded its bounds")
            if len(data) != last - first + 1:
                raise SourceReadError("Incomplete provider byte range")
            self.if_range = validator
            return bytes(data), total, validator
        finally:
            if response is not None:
                response.close()

    def _pin(self, total, cancelled):
        response = None
        pinned = tempfile.TemporaryFile(mode="w+b")
        try:
            response = self._request("GET",self._url,headers={"Accept-Encoding":"identity"},
                                     stream=True,timeout=(3,10))
            if response.status_code != 200:
                raise SourceReadError("Provider complete media unavailable")
            length = response.headers.get("Content-Length")
            if length is not None and (not re.fullmatch(r"[0-9]+",length) or int(length)!=total):
                raise SourceReadError("Provider media length changed")
            received = 0;digest = hashlib.sha256()
            for chunk in response.iter_content(self.block_size):
                if cancelled():
                    raise InterruptedError("Media read cancelled")
                if len(chunk)>total-received:
                    raise SourceReadError("Provider complete media exceeded its bounds")
                pinned.write(chunk);digest.update(chunk);received+=len(chunk)
            if cancelled():
                raise InterruptedError("Media read cancelled")
            if received!=total:
                raise SourceReadError("Incomplete provider media")
            with self.guard:
                self.pinned = pinned
                self.received = total
                self.validator = "pinned-sha256:"+digest.hexdigest()
                self.if_range = None
        except BaseException:
            pinned.close()
            raise
        finally:
            if response is not None:response.close()

    def close(self):
        """The source owner calls this after its last reader/job is released."""
        self.closed.set()
        with self.fetch_guard,self.guard:
            if self.pinned is not None:self.pinned.close();self.pinned=None
            self.blocks.clear()

    def reader(self, cancelled=lambda: False):
        return RangeReader(self, cancelled)


class RangeReader(io.RawIOBase):
    def __init__(self, source, cancelled):
        super().__init__()
        self.source, self.cancelled = source, cancelled
        self.stopped = threading.Event()
        self.position = 0

    def interrupted(self):
        return self.stopped.is_set() or self.cancelled()

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        if self.interrupted():
            raise InterruptedError("Media read cancelled")
        if whence == 2 and not self.source.size:
            self.source.block(0, self.interrupted)
        target = offset if whence == 0 else self.position + offset if whence == 1 else self.source.size + offset if whence == 2 else -1
        if target < 0:
            raise ValueError("Invalid media seek")
        self.position = target
        return target

    def read(self, size=-1):
        if self.interrupted():
            raise InterruptedError("Media read cancelled")
        if not self.source.size:
            self.source.block(0, self.interrupted)
        if size == 0 or self.position >= self.source.size:
            return b""
        # Both consumers accept short reads. Bound callback allocation even if
        # a demuxer asks for the entire remainder of a large file.
        size = min(size if size >= 0 else self.source.block_size, self.source.block_size)
        end, result = min(self.source.size, self.position + size), []
        while self.position < end:
            index, offset = divmod(self.position, self.source.block_size)
            block = self.source.block(index, self.interrupted)
            part = block[offset:offset + min(end - self.position, len(block) - offset)]
            if not part:
                raise SourceReadError("Invalid media block")
            result.append(part)
            self.position += len(part)
        return b"".join(result)

    def close(self):
        self.stopped.set()
        super().close()


@contextmanager
def open_media(source, *, cancelled=lambda: False):
    import av
    if isinstance(source, ProgressiveSource):
        with source.reader(cancelled) as reader:
            with av.open(reader, format="mp4", options=source.options()) as media:
                yield media
    else:
        with av.open(str(source)) as media:
            yield media


def source_progress(source):
    return source.snapshot() if isinstance(source, ProgressiveSource) else {"kind": "local", "complete": True}
