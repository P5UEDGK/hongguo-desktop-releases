"""Whole-episode admission; a full cache pauses work instead of evicting episodes."""
from contextlib import contextmanager
import os
from pathlib import Path
import stat
import tempfile
import threading


class CacheLimitReached(Exception):
    pass


class CacheBudget:
    def __init__(self, root, limit_bytes):
        self.root = Path(root).resolve(strict=True)
        self.limit_bytes = limit_bytes
        self.guard = threading.RLock()

    def usage(self):
        def size(path):
            try:
                info = path.lstat()
            except FileNotFoundError:
                if path == self.root:
                    raise CacheLimitReached('Video cache directory is unavailable') from None
                return 0  # A foreground session may be released during the scan.
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise CacheLimitReached('Linked cache content cannot be accounted safely')
            if stat.S_ISDIR(info.st_mode):
                try:
                    return sum(size(child) for child in path.iterdir())
                except FileNotFoundError:
                    if path == self.root:
                        raise CacheLimitReached('Video cache directory is unavailable') from None
                    return 0
            if stat.S_ISREG(info.st_mode):
                return info.st_size
            raise CacheLimitReached('Unknown cache content')
        return size(self.root)

    def check(self, extra=0):
        limit = self.limit_bytes()
        if type(extra) is not int or extra < 0 or type(limit) is not int or limit < 1:
            raise CacheLimitReached('Invalid cache reservation')
        if self.usage() + extra > limit:
            raise CacheLimitReached('Video cache limit reached')

    @contextmanager
    def admit(self, extra):
        # One source download or background conversion reserves the disk at a time.
        # Foreground playback does not wait on this lock and is never truncated.
        with self.guard:
            self.check(extra)
            yield self.check


def cache_complete_episode(budget, output, expected_bytes, fetch, convert):
    """Fetch and convert privately; publish an original only after complete validation.

    fetch(path, maximum, check) must honor the byte bound and cancellation check.
    convert(input, output) must validate/remux the complete media into output.
    The three source-sized copies reserve download/decrypt/remux peak usage.
    """
    output = Path(output)
    if output.parent.resolve() != budget.root / 'stream-cache':
        raise ValueError('Original output is outside the selected video cache')
    if type(expected_bytes) is not int or expected_bytes <= 0:
        raise CacheLimitReached('Complete episode size is unavailable')
    with budget.admit(expected_bytes * 3 + 65536) as check:
        with tempfile.TemporaryDirectory(prefix='.episode-', dir=output.parent) as temporary:
            stage = Path(temporary)
            original, complete = stage/'source.enc', stage/'complete.mp4'
            fetch(original, expected_bytes, check)
            if original.stat().st_size != expected_bytes:
                raise OSError('Incomplete episode response')
            check()
            convert(original, complete)
            if not complete.is_file() or complete.stat().st_size == 0:
                raise OSError('Incomplete episode conversion')
            check()
            # A concurrent foreground writer must own the same per-media lock.
            if output.exists():
                raise FileExistsError('Original output already exists')
            os.replace(complete, output)
        return output
