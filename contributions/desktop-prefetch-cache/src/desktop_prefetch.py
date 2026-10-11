"""Ordered source downloads overlap a single current-first HLS encoder."""
import json
import os
from pathlib import Path
import re
import threading
import uuid

from desktop_hls import EncodingCancelled
from desktop_playable_cache import PlayableEpisodeCache, CacheQuotaExceeded, OWNER, plain


class EpisodePrefetcher:
    def __init__(self, source_loader, episode_loader, cache_root, *, encoder,
                 ahead=3, status_path=None, quota_bytes=2 * 1024 ** 3, download_loader=None,
                 profile_files=None, source_status=None):
        if not isinstance(ahead, int) or isinstance(ahead, bool) or not 0 <= ahead <= 3:
            raise ValueError("Invalid prefetch window")
        self.source_loader, self.episode_loader = source_loader, episode_loader
        self.download_loader = download_loader or source_loader
        self.source_status = source_status or (lambda source: {"kind": "local", "complete": True})
        self.cache = PlayableEpisodeCache(cache_root, encoder=encoder, quota_bytes=quota_bytes, profile_files=profile_files)
        self.ahead, self.status_path = ahead, Path(status_path) if status_path else None
        self.condition = threading.Condition()
        self.report_revision = 0
        self.reporter = None
        self.generation = 0
        self.foreground = {}
        self.foreground_directories = {}
        self.cache_results = {}
        self.busy = None
        self.pending = []
        self.active = None
        self.completed = []
        self.window_keys = set()
        self.failed = []
        self.current = None
        self.current_complete = False
        self.current_source = None
        self.playback_mode = None
        self.latest_episodes = []
        self.worker = None
        self.downloader = None
        self.download_pending = []
        self.download_active = None
        self.sources = {}
        self.download_completed = []
        self.closed = False
        self.background_cancelled = threading.Event()
        self._report()

    @staticmethod
    def _episodes(episodes):
        by_index = {}
        for item in episodes:
            index, vid = item.get("index"), str(item.get("vid", ""))
            if (isinstance(index, int) and not isinstance(index, bool) and index > 0
                    and re.fullmatch(r"[0-9]{8,24}", vid)):
                by_index.setdefault(index, vid)
        return sorted(by_index.items())

    def begin(self, job, series_id, episode):
        with self.condition:
            self.generation += 1
            self.foreground[job.id] = self.generation
            job.source_loader = lambda sid, ep: self.load_source(sid, ep, job=job)
            if getattr(job, "directory", None) is not None:
                self.foreground_directories[job.id] = Path(job.directory)
            self.pending = []
            self.download_pending = []
            self.sources = {}
            self.download_completed = []
            self.completed = []
            self.window_keys = set()
            self.failed = []
            self.current = {"seriesId": str(series_id), "episode": episode}
            self.current_complete = False
            self.current_source = None
            self.playback_mode = None
            self.latest_episodes = []
            self.background_cancelled.set()
            self.condition.notify_all()
        self._report()

    def before_work(self, job):
        with self.condition:
            while True:
                if (job.cancelled.is_set() or self.closed
                        or self.foreground.get(job.id) != self.generation):
                    raise EncodingCancelled()
                if self.busy is None:
                    self.busy = job.id
                    if getattr(job, "directory", None) is not None:
                        self.foreground_directories[job.id] = Path(job.directory)
                    return
                self.condition.wait(0.1)

    def _source_complete(self, source):
        if source is None:
            return False
        try:
            return self.source_status(source).get("complete") is True
        except Exception:
            return False  # Optional status cannot invalidate an acquired source.

    def load_source(self, series_id, episode, *, job=None):
        with self.condition:
            if (self.closed or self.current != {"seriesId": str(series_id), "episode": episode}
                    or job is not None and (job.cancelled.is_set() or self.foreground.get(job.id) != self.generation)):
                raise EncodingCancelled()
            generation = self.generation
        _, metadata = self.episode_loader(series_id)
        items = self._episodes(metadata)
        vid = next((vid for index, vid in items if index == episode), None)
        if vid is None:
            raise ValueError("Episode media identity unavailable")
        with self.condition:
            if (generation != self.generation or self.closed
                    or job is not None and (job.cancelled.is_set() or self.foreground.get(job.id) != generation)
                    or self.current != {"seriesId": str(series_id), "episode": episode}):
                raise EncodingCancelled()
        source = self.source_loader(vid)
        with self.condition:
            if (generation == self.generation and not self.closed
                    and (job is None or not job.cancelled.is_set() and self.foreground.get(job.id) == generation)
                    and self.current == {"seriesId": str(series_id), "episode": episode}):
                self.latest_episodes = items
                self.sources[vid] = source
                self.current_source = source
                seen = {vid}
                for index, future_vid in items:
                    if index > episode and future_vid not in seen and len(self.download_pending) < self.ahead:
                        self.download_pending.append((generation, index, future_vid))
                        seen.add(future_vid)
                if self.download_pending and (self.downloader is None or not self.downloader.is_alive()):
                    self.downloader = threading.Thread(target=self._download, name="desktop-source-prefetch", daemon=True)
                    try:
                        self.downloader.start()
                    except RuntimeError:
                        for _, future_episode, future_vid in self.download_pending:
                            self.sources[future_vid] = None
                            if future_episode not in self.failed:
                                self.failed.append(future_episode)
                        self.download_pending = []
                        self.downloader = None
                self.condition.notify_all()
        self._report()
        return source

    def _download(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or self.download_pending)
                if self.closed:
                    return
                task = self.download_pending.pop(0)
                self.download_active = task
            self._report()
            try:
                with self.condition:
                    stale = self.closed or task[0] != self.generation
                    if stale:
                        self.download_active = None
                        self.condition.notify_all()
                if stale:
                    self._report()
                    continue
                source = self.download_loader(task[2])
            except Exception:
                source = None
            with self.condition:
                if task[0] == self.generation and not self.closed:
                    self.sources[task[2]] = source
                    if source is not None:
                        self.download_completed.append(task[1])
                    elif task[1] not in self.failed:
                        self.failed.append(task[1])
                self.download_active = None
                self.condition.notify_all()
            self._report()

    def finish(self, job, series_id, episode, source):
        with self.condition:
            expected = self.foreground.get(job.id)
            cached_result = self.cache_results.pop(job.id, None)
            self.foreground_directories.pop(job.id, None)
        mode = getattr(job, "video_mode", "h264")
        # Validation hashes source/media bytes. Never hold the scheduling lock for I/O.
        def cancelled():
            with self.condition:
                return self.closed or job.cancelled.is_set() or expected != self.generation
        current_complete, current_key = False, None
        try:
            if expected is not None and source is not None and mode != "native" and not job.failed and not cancelled():
                current_complete = cached_result if cached_result is not None else self.cache.contains(source, mode, cancelled=cancelled)
                if current_complete:current_key = self.cache._identity(source, mode, cancelled)[0]
        except Exception:
            pass  # Completion bookkeeping still releases the old foreground slot.
        with self.condition:
            generation = self.foreground.pop(job.id, None)
            if self.busy == job.id:
                self.busy = None
            if generation == self.generation and (job.failed or job.cancelled.is_set()):
                self.download_pending = []
            if (generation == self.generation and not self.closed and not job.failed
                    and not job.cancelled.is_set() and source is not None):
                mode = getattr(job, "video_mode", "h264")
                self.playback_mode = mode
                if mode == "native" or not self.cache.available:
                    # Downloaded originals already serve native playback.
                    # Neither AAC-LC nor HE-AAC needs an additional HLS copy.
                    self.pending = []
                    self.current_complete = False  # This field describes HLS completeness.
                else:
                    self.current_complete = current_complete
                    if current_key is not None:self.window_keys.add(current_key)
                    selected, seen = [], set()
                    current_vid = next((vid for index, vid in self.latest_episodes if index == episode), None)
                    if current_vid:
                        seen.add(current_vid)
                        if not self.current_complete and (getattr(job, "start_seconds", 0)
                                or not (job.directory / "complete.marker").is_file()):
                            selected.append((episode, current_vid))
                    future_count = 0
                    for index, vid in self.latest_episodes:
                        if index > episode and vid not in seen and future_count < self.ahead:
                            selected.append((index, vid))
                            seen.add(vid)
                            future_count += 1
                    self.pending = [(generation, index, vid, mode) for index, vid in selected]
                    if self.pending and (self.worker is None or not self.worker.is_alive()):
                        self.worker = threading.Thread(target=self._run, name="desktop-playable-prefetch", daemon=True)
                        try:
                            self.worker.start()
                        except RuntimeError:
                            self.failed.extend(task[1] for task in self.pending)
                            self.pending = []
                            self.worker = None
            self.condition.notify_all()
        self._report()

    def _run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or (
                    self.pending and self.pending[0][2] in self.sources
                    and self.generation not in self.foreground.values() and self.busy is None))
                if self.closed:
                    return
                task = self.pending.pop(0)
                self.active = task
                self.busy = "background"
                self.background_cancelled = threading.Event()
                cancel = self.background_cancelled
                source = self.sources[task[2]]
                protected = set(self.window_keys)
            self._report()
            failed, cancelled, window_full = False, False, False
            temporary = self.cache.root / ("stage-" + uuid.uuid4().hex)
            stage_started = False
            try:
                if not self.cache.available:
                    raise EncodingCancelled()
                if source is None:
                    raise OSError("Source preparation failed")
                if cancel.is_set():
                    raise EncodingCancelled()
                mode = task[3]
                identity_result = self.cache._identity(source, mode, cancel.is_set)
                if not self.cache.contains(source, mode, cancelled=cancel.is_set, _identity_result=identity_result):
                    extra = {"video_mode": "copy"} if mode == "copy" else {}
                    if temporary.exists():
                        raise ValueError("Prefetch stage already exists")
                    stage_started = True
                    self.cache.encoder(source, temporary, cancelled=cancel.is_set, **extra)
                    (temporary / "owner.marker").write_text(OWNER, encoding="ascii")
                    stored = self.cache.store(source, temporary, cancel.is_set, video_mode=mode, _identity_result=identity_result, protected=protected)
                    if stored is None:raise OSError("Playable cache store unavailable")
                if cancel.is_set():
                    raise EncodingCancelled()
                with self.condition:
                    if task[0] == self.generation:self.window_keys.add(identity_result[0])
            except CacheQuotaExceeded:
                cancelled, window_full = True, True
            except EncodingCancelled:
                cancelled = True
            except Exception:
                failed = True
            finally:
                try:
                    if stage_started and temporary.exists():
                        if (temporary.parent != self.cache.root or not plain(temporary)
                                or not re.fullmatch(r"stage-[0-9a-f]{32}", temporary.name)):
                            raise ValueError("Unsafe prefetch stage")
                        # This nonce path was absent before our encoder call.
                        # Its known outputs can be unlinked without allocating
                        # a marker on a full disk; unknown content is retained.
                        self.cache._remove_fresh_stage(temporary)
                except (OSError, ValueError):
                    failed = True
                with self.condition:
                    if task[0] == self.generation and window_full:self.pending = []
                    if task[0] == self.generation and not cancelled:
                        if task[1] == self.current["episode"]:
                            self.current_complete = not failed
                            if failed:
                                if task[1] not in self.failed:
                                    self.failed.append(task[1])
                                self.pending = []
                        else:
                            outcomes = self.failed if failed else self.completed
                            if task[1] not in outcomes:
                                outcomes.append(task[1])
                    self.active = None
                    self.busy = None
                    self.condition.notify_all()
                self._report()

    def encode(self, *args, **kwargs):
        cancelled = kwargs.pop("cancelled", lambda: False)
        result = self.cache.encode(*args, cancelled=lambda: self.closed or cancelled(), **kwargs)
        directory = Path(args[1] if len(args)>1 else kwargs['directory'])
        with self.condition:
            for identifier, target in self.foreground_directories.items():
                if target == directory: self.cache_results[identifier] = result
        return result

    def snapshot(self):
        with self.condition:
            source = self.current_source
            result = {
                "schema": 2, "processId": os.getpid(), "ahead": self.ahead,
                "cacheKind": "original-media" if self.playback_mode == "native" else "complete-playable-hls",
                "playbackMode": self.playback_mode,
                "currentSourceComplete": False,
                "current": self.current,
                "currentPlayableComplete": self.current_complete,
                "foregroundRequests": len(self.foreground),
                "pendingEpisodes": [task[1] for task in self.pending],
                "activeEpisode": self.active[1] if self.active else None,
                "completedEpisodes": list(self.completed), "failedEpisodes": list(self.failed),
                "downloadCompletedEpisodes": list(self.download_completed),
                "downloadPendingEpisodes": [task[1] for task in self.download_pending],
                "downloadActiveEpisode": self.download_active[1] if self.download_active else None,
                "failureCode": "preparation-failed" if self.failed else None,
                "state": "closed" if self.closed else "preparing" if (
                    self.foreground or self.pending or self.active or self.download_pending
                    or self.download_active) else "idle",
            }

        result["currentSourceComplete"] = self._source_complete(source)
        return result
    def _report(self):
        if self.status_path is None:
            return
        with self.condition:
            self.report_revision += 1
            if self.reporter is None or not self.reporter.is_alive():
                self.reporter = threading.Thread(target=self._write_reports, name="desktop-prefetch-report", daemon=True)
                try:
                    self.reporter.start()
                except RuntimeError:
                    self.reporter = None  # Diagnostics must not fail playback.
            self.condition.notify_all()

    def _write_reports(self):
        # One writer coalesces requests; optional host I/O never occupies an
        # encoder/downloader worker, and old snapshots cannot publish last.
        handled = 0
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.report_revision > handled)
                revision = self.report_revision
                generation = self.generation
            try:
                value = self.snapshot()
                with self.condition:
                    fresh = revision == self.report_revision and generation == self.generation
                if fresh:
                    temporary = self.status_path.with_suffix(".json.tmp")
                    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
                    os.replace(temporary, self.status_path)
            except Exception:
                pass
            handled = revision
            with self.condition:
                if self.closed and handled == self.report_revision:
                    self.reporter = None
                    return

    def wait_idle(self, timeout=30):
        with self.condition:
            return self.condition.wait_for(lambda: not self.foreground and not self.pending
                                           and self.active is None and not self.download_pending
                                           and self.download_active is None, timeout=timeout)

    def close(self):
        with self.condition:
            self.closed = True
            self.pending = []
            self.download_pending = []
            self.background_cancelled.set()
            self.condition.notify_all()
        self._report()
        if self.worker and self.worker is not threading.current_thread():
            self.worker.join(timeout=2)
        if self.downloader and self.downloader is not threading.current_thread():
            self.downloader.join(timeout=2)
        reporter = self.reporter
        if reporter and reporter is not threading.current_thread():
            reporter.join(timeout=2)
