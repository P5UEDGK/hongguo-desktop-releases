"""Plan CRF/VBV against the existing HLS disk quota; no URLs or transport logic."""
import math
from pathlib import Path
import re
import threading


class EncodingBudgetExceeded(ValueError):
    """Fixed, non-sensitive classification of an exhausted output budget."""


class _BudgetFile:
    def __init__(self, budget, file, path):
        self.budget, self.file, self.path = budget, file, path
        self.extent = 0

    def __getattr__(self, name):
        return getattr(self.file, name)

    def write(self, data):
        with self.budget.guard:
            self.budget.check()
            end = self.file.tell() + len(data)
            charge = max(0, end - self.extent)
            if charge > self.budget.remaining:
                self.budget.exceeded = True
                raise EncodingBudgetExceeded("Desktop output budget exceeded")
            # Reserve actual extent growth before the unbuffered disk write.
            self.budget.remaining -= charge
            self.extent = max(self.extent,end)
            self.budget.extents[self.path] = self.extent
            return self.file.write(data)


class OutputBudget:
    """PyAV multi-file I/O guard; reject bytes before they reach the disk."""
    def __init__(self, directory, max_output_bytes, cancelled=lambda: False):
        if type(max_output_bytes) is not int or max_output_bytes <= len(b"desktop-hls-v1\n"):
            raise EncodingBudgetExceeded("Desktop output budget exceeded")
        self.directory = Path(directory).resolve(strict=True)
        self.remaining = max_output_bytes - len(b"desktop-hls-v1\n")
        self.extents = {}
        self.cancelled = cancelled
        self.exceeded = False
        self.guard = threading.Lock()

    def check(self):
        if self.exceeded:
            raise EncodingBudgetExceeded("Desktop output budget exceeded")
        if self.cancelled():
            from desktop_hls import EncodingCancelled
            raise EncodingCancelled("Desktop encode cancelled")

    def open(self, url, flags, options):
        self.check()
        path = Path(url[5:] if url.startswith("file:") else url)
        if not path.is_absolute():
            path = self.directory / path
        path = path.resolve()
        if path.parent != self.directory or not re.fullmatch(r"(?:index\.m3u8|init\.mp4|seg[0-9]{6}\.m4s)(?:\.tmp)?", path.name):
            raise ValueError("Invalid desktop output path")
        if flags & 2:  # AVIO_FLAG_WRITE
            with self.guard:
                self.check()
                # FFmpeg renames .tmp to the final path outside this callback.
                # Reconcile just this logical pair; segment accounting stays O(1).
                final = path.with_suffix('') if path.name.endswith('.tmp') else path
                temporary = final.with_name(final.name+'.tmp')
                for sibling in (final,temporary):
                    actual = sibling.stat().st_size if sibling.exists() else 0
                    self.remaining += self.extents.get(sibling,0) - actual
                    self.extents[sibling] = actual
                previous = self.extents[path]
                file = path.open("w+b", buffering=0)
                self.remaining += previous  # Opening truncated this path.
                self.extents[path] = 0
                return _BudgetFile(self, file, path)
        return path.open("rb", buffering=0)


def video_budget_options(duration_seconds, audio_bitrates, max_output_bytes, *, fixed_audio_bitrates=()):
    """Leave 10% plus 64 KiB for muxing, copy audio, and a two-second VBV.

    This is a rate-control plan, not a replacement for actual byte checks.
    Unknown duration retains the previous CRF policy and its hard disk guard.
    Resolution, frame timing, CRF target, and copied AAC packets stay unchanged.
    VBV can increase quantization when the budget binds; quality is not identical.
    """
    if (not isinstance(max_output_bytes, int) or isinstance(max_output_bytes, bool)
            or max_output_bytes <= 0):
        raise ValueError("Invalid desktop output budget")
    if (not isinstance(duration_seconds, (int, float)) or isinstance(duration_seconds, bool)
            or not math.isfinite(duration_seconds) or duration_seconds <= 0):
        return {}
    # Metadata can omit AAC bitrates. Reserve at least 256 kbit/s per track;
    # retain the byte guard if metadata or the actual stream exceeds estimates.
    audio_rate = 0
    for rate in fixed_audio_bitrates:
        if type(rate) is not int or rate <= 0:
            raise ValueError("Invalid fixed audio bitrate")
        audio_rate += rate
    for rate in audio_bitrates:
        if not isinstance(rate, int) or isinstance(rate, bool) or rate <= 0:
            rate = 256_000
        audio_rate += max(256_000, rate)
    audio_bytes = audio_rate * (duration_seconds + 2) / 8
    video_bytes = max_output_bytes * 0.90 - 65_536 - audio_bytes
    max_kbps = math.floor(video_bytes * 8 / ((duration_seconds + 2) * 1000))
    if max_kbps < 64:
        raise EncodingBudgetExceeded("Desktop segment budget cannot fit this duration")
    return {"x264-params": f"vbv-maxrate={max_kbps}:vbv-bufsize={2 * max_kbps}"}
