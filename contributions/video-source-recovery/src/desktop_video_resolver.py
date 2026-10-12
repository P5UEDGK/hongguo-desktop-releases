"""Bounded provider model resolution; no credentials, transport or disk state."""
from collections import OrderedDict
import copy
import json
import threading
import time


class ModelUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("Media model unavailable")


class VideoModelResolver:
    batch_path = "/novel/player/multi_video_model/v1/"
    single_path = "/novel/player/video_model/v1/"
    biz_param = {"detail_page_version": 0, "device_level": 3,
                 "disable_digg_stat": False, "disable_video_relate_book": False,
                 "need_all_video_definition": True, "need_mp4_align": False,
                 "use_os_player": False, "use_server_dns": False, "video_platform": 1024}

    def __init__(self, api, *, empty_error, clock=time.monotonic, wall=time.time):
        self.api, self.empty_error = api, empty_error
        self.clock, self.wall = clock, wall
        self.lock = threading.RLock()
        self.cache = OrderedDict()
        self.batch_after = 0.0
        self.max_entries = 128
        self.ttl = 300.0

    @staticmethod
    def _model(value, vid):
        if not isinstance(value, dict):
            return None
        model = value.get("video_model")
        if isinstance(model, str):
            try:
                model = json.loads(model)
            except (ValueError, TypeError):
                return None
        if not isinstance(model, dict) or not model.get("video_list"):
            return None
        # model.video_id is the VOD object's identifier, not the requested
        # episode ID. Binding comes from the batch map key/single request.
        return model

    def _store(self, vid, model, entry):
        now = self.wall()
        expires = []
        for value in (entry.get("expire_time"), model.get("url_expire")):
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
            if value > 0:
                expires.append(value)
        ttl = min([self.ttl] + [value - now - 60 for value in expires])
        if expires and min(expires) <= now:
            raise ModelUnavailable()
        if ttl > 0:
            self.cache[vid] = (self.clock() + ttl, copy.deepcopy(model))
            self.cache.move_to_end(vid)
            while len(self.cache) > self.max_entries:
                self.cache.popitem(last=False)

    def resolve(self, vids, *, force=False):
        ids = list(dict.fromkeys(str(v) for v in vids))
        if len(ids) > 5:
            raise ValueError("Resolve at most five models per call")
        out = {}
        # Network calls under this lock coalesce the foreground/prefetch race.
        # Host transport retains its own timeout and global throttle.
        with self.lock:
            missing = []
            for vid in ids:
                item = self.cache.get(vid)
                if not force and item and item[0] > self.clock():
                    self.cache.move_to_end(vid)
                    out[vid] = copy.deepcopy(item[1])
                else:
                    self.cache.pop(vid, None)
                    missing.append(vid)
            if missing and self.clock() >= self.batch_after:
                try:
                    response = self.api("POST", self.batch_path, body={
                        "biz_param": dict(self.biz_param), "mixed_video_id_map": {"1": missing}},
                        max_retries=1)
                except self.empty_error as error:
                    # Only the observed 200/empty failure permits fallback.
                    # Auth/risk/429/transport errors must propagate unchanged.
                    if getattr(error, "diagnostic", {}) != {"http_status": 200, "body_bytes": 0}:
                        raise
                    response = {}
                if isinstance(response, dict) and response.get("code") not in (None, 0):
                    raise ModelUnavailable()
                data = response.get("data") if isinstance(response, dict) else None
                for vid in missing:
                    entry = data.get(vid) if isinstance(data, dict) else None
                    model = self._model(entry, vid)
                    if model is not None:
                        out[vid] = model
                        self._store(vid, model, entry)
                if any(vid not in out for vid in missing):
                    self.batch_after = self.clock() + 300.0
            for vid in missing:
                if vid in out:
                    continue
                response = self.api("POST", self.single_path, body={
                    "video_id": vid, "content_type": 1, "biz_param": dict(self.biz_param)},
                    max_retries=1)
                if isinstance(response, dict) and response.get("code") not in (None, 0):
                    raise ModelUnavailable()
                entry = response.get("data") if isinstance(response, dict) else None
                model = self._model(entry, vid)
                if model is None:
                    raise ModelUnavailable()
                out[vid] = model
                self._store(vid, model, entry)
        return out


def media_urls(track):
    """Ordered, deduplicated URLs already normalized by the host adapter."""
    fields = ["main_url", "backup_url"] + sorted(
        (name for name in track if name.startswith("backup_url_") and name[11:].isdigit()),
        key=lambda name: int(name[11:]))
    return list(dict.fromkeys(track[name] for name in fields if track.get(name)))[:4]
