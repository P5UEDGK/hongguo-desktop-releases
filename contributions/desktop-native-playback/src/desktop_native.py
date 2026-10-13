"""Local HEVC player owned by the desktop session, with bounded recovery.

Only the authenticated HLS adapter supplies source paths. The client cannot
choose a process, HWND, device, file, mpv option or command string.
"""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import math
import os
from pathlib import Path
import queue
from collections import deque, OrderedDict
import threading
import time
from desktop_stream import ProgressiveSource, SourceReadError
from desktop_native_engine import EnginePool
import uuid

DLL_SHA256 = "34780746a0273a4fcae42dfe262a28984a426a238939474afd3a1561b450bbef"


def validate_control(body):
    if not isinstance(body, dict) or not body or set(body) - {
            "paused", "rate", "volume", "muted", "seek", "rect", "visible"}:
        raise ValueError("Invalid native control")
    for name in ("paused", "muted", "visible"):
        if name in body and type(body[name]) is not bool:
            raise ValueError("Invalid native flag")
    for name, low, high in (("rate", .25, 4), ("volume", 0, 1), ("seek", 0, 86400)):
        if name in body:
            value = body[name]
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError("Invalid native number")
    if "rect" in body:
        rect = body["rect"]
        if (not isinstance(rect, list) or len(rect) != 4
                or any(type(v) is not int or not 0 <= v <= 32768 for v in rect)
                or rect[2] < 1 or rect[3] < 1):
            raise ValueError("Invalid native rectangle")
    return dict(body)


class Event(C.Structure):
    _fields_ = [("id", C.c_int), ("error", C.c_int), ("reply", C.c_uint64), ("data", C.c_void_p)]


class Mpv:
    def __init__(self, dll):
        self.dll = dll
        self.handle = dll.mpv_create()
        if not self.handle:
            raise RuntimeError("Native player unavailable")

    @staticmethod
    def check(result):
        if result < 0:
            raise RuntimeError("Native player operation failed")

    def option(self, name, value):
        self.check(self.dll.mpv_set_option_string(self.handle, name.encode(), str(value).encode()))

    def command(self, *args):
        encoded = [str(value).encode("utf-8") for value in args]
        self.check(self.dll.mpv_command(self.handle, (C.c_char_p * (len(args) + 1))(*encoded, None)))

    def get(self, name):
        pointer = self.dll.mpv_get_property_string(self.handle, name.encode())
        if not pointer:
            return None
        try:
            return C.string_at(pointer).decode("utf-8", errors="replace")
        finally:
            self.dll.mpv_free(pointer)

    def number(self, name, default=0):
        try:
            value = float(self.get(name))
            return value if math.isfinite(value) else default
        except (TypeError, ValueError):
            return default

    def close(self):
        if self.handle:
            self.dll.mpv_terminate_destroy(self.handle)
            self.handle = None


def audio_output_ready(description, player):
    """Video-only sources need no AO; expected audio must decode and open output."""
    return not (description or {}).get("audio") or (
        player.get("current-ao") == "wasapi" and player.get("audio-params") not in (None, "", "null"))


class NativeHost:
    def __init__(self, *, parent_pid=None, dll_path=None, hardware=True):
        self.hardware = hardware
        self.decode_preferences = DecoderPreferences()
        self.parent_pid = os.getppid() if parent_pid is None else parent_pid
        self.sessions = {}
        self.guard = threading.RLock()
        self.available = False
        self.engine_pool = EnginePool(self._close_engine, self._pump_engine)
        if os.name != "nt":
            return
        path = Path(dll_path) if dll_path else Path(__file__).parent / "native/libmpv-2.dll"
        try:
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != DLL_SHA256:
                return
            self.dll = C.CDLL(str(path.resolve()))
            definitions = {
                "mpv_create": ([], C.c_void_p),
                "mpv_set_option_string": ([C.c_void_p, C.c_char_p, C.c_char_p], C.c_int),
                "mpv_initialize": ([C.c_void_p], C.c_int),
                "mpv_command": ([C.c_void_p, C.POINTER(C.c_char_p)], C.c_int),
                "mpv_wait_event": ([C.c_void_p, C.c_double], C.POINTER(Event)),
                "mpv_get_property_string": ([C.c_void_p, C.c_char_p], C.c_void_p),
                "mpv_free": ([C.c_void_p], None),
                "mpv_terminate_destroy": ([C.c_void_p], None),
            }
            for name, (args, result) in definitions.items():
                function = getattr(self.dll, name)
                function.argtypes, function.restype = args, result
            self.user = C.WinDLL("user32", use_last_error=True)
            self.enum_callback = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
            self.window_callback = C.WINFUNCTYPE(C.c_ssize_t, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
            definitions = {
                "EnumWindows": ([self.enum_callback, W.LPARAM], W.BOOL),
                "EnumChildWindows": ([W.HWND, self.enum_callback, W.LPARAM], W.BOOL),
                "GetClassNameW": ([W.HWND, W.LPWSTR, C.c_int], C.c_int),
                "SetWindowLongPtrW": ([W.HWND, C.c_int, C.c_void_p], C.c_void_p),
                "CallWindowProcW": ([C.c_void_p, W.HWND, W.UINT, W.WPARAM, W.LPARAM], C.c_ssize_t),
                "PostMessageW": ([W.HWND, W.UINT, W.WPARAM, W.LPARAM], W.BOOL),
                "MapWindowPoints": ([W.HWND, W.HWND, C.POINTER(W.POINT), W.UINT], C.c_int),
                "GetWindowThreadProcessId": ([W.HWND, C.POINTER(W.DWORD)], W.DWORD),
                "GetWindow": ([W.HWND, W.UINT], W.HWND),
                "IsWindow": ([W.HWND], W.BOOL),
                "IsWindowVisible": ([W.HWND], W.BOOL),
                "GetClientRect": ([W.HWND, C.POINTER(W.RECT)], W.BOOL),
                "SetProcessDpiAwarenessContext": ([C.c_void_p], W.BOOL),
                "SetThreadDpiAwarenessContext": ([C.c_void_p], C.c_void_p),
                "CreateWindowExW": ([W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, C.c_int,
                    C.c_int, C.c_int, C.c_int, W.HWND, W.HMENU, W.HINSTANCE, C.c_void_p], W.HWND),
                "SetWindowPos": ([W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT], W.BOOL),
                "ShowWindow": ([W.HWND, C.c_int], W.BOOL),
                "DestroyWindow": ([W.HWND], W.BOOL),
                "PeekMessageW": ([C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT], W.BOOL),
                "TranslateMessage": ([C.POINTER(W.MSG)], W.BOOL),
                "DispatchMessageW": ([C.POINTER(W.MSG)], C.c_ssize_t),
            }
            for name, (args, result) in definitions.items():
                function = getattr(self.user, name)
                function.argtypes, function.restype = args, result
            self.user.SetProcessDpiAwarenessContext(C.c_void_p(-4))
            self.available = True
        except (OSError, AttributeError):
            self.available = False

    def _pump_engine(self):
        message = W.MSG()
        while self.user.PeekMessageW(C.byref(message), None, 0, 0, 1):
            self.user.TranslateMessage(C.byref(message))
            self.user.DispatchMessageW(C.byref(message))

    def _close_engine(self, resources):
        player, hwnd = resources.get("player"), resources.get("hwnd")
        try:
            if player:
                player.close()
        finally:
            if hwnd and self.user.IsWindow(hwnd):
                self.user.DestroyWindow(hwnd)
            resources.clear()

    def close(self):
        with self.guard:
            sessions = list(self.sessions.items())
        for identifier, session in sessions:
            self.release(identifier)
        return self.engine_pool.close()

    def parent_window(self):
        windows = []
        @self.enum_callback
        def collect(hwnd, _):
            pid = W.DWORD()
            self.user.GetWindowThreadProcessId(hwnd, C.byref(pid))
            if pid.value == self.parent_pid and not self.user.GetWindow(hwnd, 4):
                rect = W.RECT()
                if self.user.GetClientRect(hwnd, C.byref(rect)) and rect.right > 100 and rect.bottom > 100:
                    windows.append((bool(self.user.IsWindowVisible(hwnd)), rect.right * rect.bottom, hwnd))
            return True
        self.user.EnumWindows(collect, 0)
        if not windows:
            raise RuntimeError("Desktop parent window unavailable")
        return max(windows, key=lambda item: item[:2])[2]

    def prepare(self, job):
        if not self.available or job.cancelled.is_set():
            raise RuntimeError("Native player unavailable")
        with self.guard:
            if job.cancelled.is_set():
                raise RuntimeError("Native job cancelled")
            for identifier, previous in list(self.sessions.items()):
                if previous.close() is False:
                    raise RuntimeError("Previous native session is stopping")
                self.sessions.pop(identifier, None)
            session = NativeSession(self, job, self.parent_window())
            self.sessions[job.id] = session
            try:
                session.thread.start()
                if job.cancelled.is_set():
                    raise RuntimeError("Native job cancelled")
            except BaseException:
                if session.close() is not False:
                    self.sessions.pop(job.id, None)
                raise

    def snapshot(self, identifier):
        with self.guard:
            session = self.sessions.get(identifier)
            return session.snapshot() if session else {"state": "failed", "failureCode": "native-unavailable"}

    def control(self, identifier, body):
        body = validate_control(body)
        with self.guard:
            session = self.sessions.get(identifier)
            if not session or session.stop.is_set():
                raise ValueError("Native session unavailable")
            return session.submit(body)

    def release(self, identifier):
        with self.guard:
            session = self.sessions.get(identifier)
        if session and session.close() is False:
            return False
        with self.guard:
            if self.sessions.get(identifier) is session:
                self.sessions.pop(identifier, None)
        return True


class DecoderPreferences:
    """Process-local successful hwdec choices, never a permanent capability ban.

    The host fixes DLL/renderer/adapter configuration for its lifetime. A new
    host (including app/driver restart) starts empty. Every file still verifies
    its own decoded frame; this only skips re-probing unrelated hwdec methods.
    """
    def __init__(self, limit=64):
        self.limit = limit
        self.choices = OrderedDict()
        self.guard = threading.Lock()

    @staticmethod
    def key(description):
        video = (description or {}).get("video") or {}
        fields = tuple(video.get(k) for k in ("contentType", "pixelFormat", "width", "height"))
        if (not all(isinstance(v, str) and v for v in fields[:2])
                or not all(type(v) is int and v > 0 for v in fields[2:])):
            return None
        return fields

    def select(self, description, hardware=True):
        if not hardware:
            return "no", False
        key = self.key(description)
        with self.guard:
            mode = self.choices.get(key)
            if mode:
                self.choices.move_to_end(key)
        return (mode, True) if mode else ("auto-safe", False)

    def remember(self, description, mode):
        key = self.key(description)
        if key is None or not mode or mode in ("no", "auto", "auto-safe"):
            return
        with self.guard:
            self.choices[key] = mode
            self.choices.move_to_end(key)
            while len(self.choices) > self.limit:
                self.choices.popitem(last=False)

    def forget(self, description):
        with self.guard:
            self.choices.pop(self.key(description), None)


class NativeOutputError(RuntimeError):
    """Audio/render/input output failure, distinct from decoder failure."""


class FrameDropWatch:
    def __init__(self):
        self.samples=deque()
        self.growth=None

    def observe(self, now, output_drops, decoder_drops, fps, rate, active):
        # VO drops include refresh-rate/rendering limits, not decode errors.
        total=max(0,decoder_drops)
        if not active or self.samples and total < self.samples[-1][1]:
            self.samples.clear();self.growth=None
        if not active:
            return False
        if self.samples and total>self.samples[-1][1]:self.growth=now
        self.samples.append((now,total))
        while len(self.samples)>2 and self.samples[1][0]<=now-2:self.samples.popleft()
        elapsed=now-self.samples[0][0]
        return (elapsed>=2 and self.growth is not None and now-self.growth<=.5
                and total-self.samples[0][1]>=max(10,max(1,fps)*max(.25,rate)*elapsed*.5))


class NativeSession:
    def __init__(self, host, job, parent):
        self.host, self.job, self.parent = host, job, parent
        self.stop = threading.Event()
        self.commands = queue.Queue(maxsize=64)
        self.guard = threading.Lock()
        self.revision = 0
        self.data = {"state": "preparing", "time": job.start_seconds, "duration": job.duration,
                     "paused": True, "rate": 1, "volume": 1, "muted": False, "seeking": False,
                     "width": 0, "height": 0, "decoder": "probing", "revision": 0,
                     "hardwareAttempted": host.hardware, "softwareRetried": False}
        self.engine_resources = None
        pool = getattr(host, "engine_pool", None)
        self.thread = (pool.task(self) if pool else
                       threading.Thread(target=self.run, name="desktop-native-player", daemon=True))
        self.input_hooks = {}
        self.queued_state = {"paused": True, "rate": 1, "volume": 1, "muted": False}

    def forward_input(self, container):
        """Forward native input to the existing WebView, preserving its trusted
        fullscreen/keyboard behavior and avoiding a second control state machine.
        Both targets are discovered exclusively inside the owned desktop root.
        """
        user = self.host.user
        # Windows hit testing can return the outer STATIC container itself,
        # including when the renderer has no child HWND under the pointer.
        widgets, surfaces = [], [container]
        @self.host.enum_callback
        def collect(hwnd, _):
            name = C.create_unicode_buffer(256)
            user.GetClassNameW(hwnd, name, 256)
            if name.value == "Chrome_RenderWidgetHostHWND":
                widgets.append(hwnd)
            return True
        user.EnumChildWindows(self.parent, collect, 0)
        @self.host.enum_callback
        def video(hwnd, _):
            surfaces.append(hwnd)
            return True
        user.EnumChildWindows(container, video, 0)
        if not widgets or not surfaces:
            return False
        widget = widgets[0]
        for surface in surfaces:
            if surface in self.input_hooks:
                continue
            original = [None]
            @self.host.window_callback
            def procedure(hwnd, message, wparam, lparam, target=widget, previous=original):
                if message == 0x0084 and hwnd == container:  # WM_NCHITTEST
                    # STATIC defaults to HTTRANSPARENT without SS_NOTIFY.
                    # Own the hit so Windows delivers real pointer input here.
                    return 1  # HTCLIENT
                if message == 0x0021:  # WM_MOUSEACTIVATE: keep focus in WebView2.
                    return 3  # MA_NOACTIVATE
                if 0x0200 <= message <= 0x020E or message in (0x0100,0x0101,0x0102,0x0104,0x0105,0x0106):
                    if 0x0200 <= message <= 0x0209 or message in (0x020B,0x020C,0x020D):
                        point = W.POINT(C.c_short(lparam & 0xffff).value,
                                        C.c_short((lparam >> 16) & 0xffff).value)
                        user.MapWindowPoints(hwnd, target, C.byref(point), 1)
                        lparam = (point.x & 0xffff) | ((point.y & 0xffff) << 16)
                    user.PostMessageW(target, message, wparam, lparam)
                    return 0
                return user.CallWindowProcW(previous[0], hwnd, message, wparam, lparam)
            previous = user.SetWindowLongPtrW(surface, -4, C.cast(procedure, C.c_void_p))
            if not previous:
                raise RuntimeError("Native input bridge unavailable")
            original[0] = previous
            self.input_hooks[surface] = (previous, procedure)
        return True

    def snapshot(self):
        with self.guard:
            return dict(self.data)

    def desired_state(self):
        with self.guard:
            return dict(self.queued_state)

    def submit(self, command):
        with self.guard:
            revision = self.revision + 1
            self.commands.put_nowait((revision, command))
            self.revision = revision
            self.queued_state.update({key: value for key, value in command.items()
                                      if key in self.queued_state})
            return revision

    def close(self):
        self.stop.set()
        if self.thread.is_alive() and self.thread is not threading.current_thread():
            self.thread.join(timeout=3)
        return not self.thread.is_alive()

    def run(self):
        player = None
        hwnd = None
        user = self.host.user
        initial = time.monotonic()
        grace = initial + 3
        last_progress, last_position, slow_since = initial, None, None
        retried = False
        frame_ready = False
        requested_position = self.job.start_seconds
        drop_watch = FrameDropWatch()
        description = getattr(self.job, "source_description", None)
        preferences = getattr(self.host, "decode_preferences", None)
        selected_hwdec, cache_hit = (preferences.select(description, self.host.hardware)
            if preferences else ("auto-safe" if self.host.hardware else "no", False))
        observed_hwdec = None
        fallback_reason = None
        progressive = isinstance(self.job.source, ProgressiveSource)
        media_uri = str(self.job.source) if not progressive else self.job.stream_url
        # Starting paused allows the frontend to place the surface and apply
        # its remembered speed/volume before either picture or sound advances.
        desired = {"paused": True, "rate": 1, "volume": 1, "muted": False}
        def retry_software(*, no_frame=False, reason="decode-error"):
            nonlocal retried, initial, grace, last_progress, slow_since, frame_ready, fallback_reason
            if retried or player.get("hwdec-current") == "no":
                raise RuntimeError("Software decoding failed")
            retried = True
            fallback_reason = reason
            if preferences:
                preferences.forget(description)
            frame_ready = False
            position = requested_position if no_frame else player.number("time-pos", self.job.start_seconds)
            drop_watch.samples.clear();drop_watch.growth=None
            player.command("set", "hwdec", "no")
            player.command("set", "start", position)
            player.command("loadfile", media_uri)
            for key, option in (("paused", "pause"), ("rate", "speed"), ("volume", "volume"), ("muted", "mute")):
                value = desired[key]
                player.command("set", option, "yes" if value is True else "no" if value is False else value * 100 if key == "volume" else value)
            initial = last_progress = time.monotonic()
            grace, slow_since = initial + 3, None
            with self.guard:
                self.data.update(state="preparing", softwareRetried=True, hardwareFallbackReason=reason)
        try:
            user.SetThreadDpiAwarenessContext(C.c_void_p(-4))
            resources = self.engine_resources
            reused = bool(resources and resources.get("player"))
            if reused:
                player, hwnd = resources["player"], resources["hwnd"]
                if resources["parent"] != self.parent or not user.IsWindow(hwnd):
                    self.host._close_engine(resources)
                    player, hwnd, reused = None, None, False
            if not reused:
                hwnd = user.CreateWindowExW(0x08000000, "STATIC", "Hongguo native video",
                                           0x40000000 | 0x04000000 | 0x02000000,
                                           0, 0, 1, 1, self.parent, None, None, None)
                if not hwnd:
                    raise RuntimeError("Native surface unavailable")
                player = Mpv(self.host.dll)
                options = {"config": "no", "load-scripts": "no", "osc": "no", "terminal": "no",
                           "input-default-bindings": "no", "input-vo-keyboard": "no",
                           "idle": "yes", "force-window": "yes", "keep-open": "yes", "pause": "yes",
                           "hwdec-software-fallback": "3", "vo": "gpu",
                           "gpu-api": "d3d11", "gpu-context": "d3d11", "wid": int(hwnd),
                           "ao": "wasapi", "audio-exclusive": "no", "video-sync": "audio",
                           "audio-pitch-correction": "yes", "priority": "abovenormal",
                           "framedrop": "vo", "vd-lavc-threads": "0"}
                for key, value in options.items():
                    player.option(key, value)
                player.check(player.dll.mpv_initialize(player.handle))
                if resources is not None:
                    resources.update(player=player, hwnd=hwnd, parent=self.parent, id=uuid.uuid4().hex)
            # Every source-dependent option is reset, including when switching
            # encrypted/clear input or recovering from the previous soft retry.
            per_file = {"start": self.job.start_seconds, "pause": "yes", "speed": 1,
                        "volume": 100, "mute": "yes" if desired["muted"] else "no",
                        "hwdec": selected_hwdec,
                        "cache": "yes" if progressive else "auto", "cache-secs": "12",
                        "demuxer-readahead-secs": "12", "demuxer-max-bytes": "32MiB",
                        "cache-on-disk": "no", "cache-pause": "yes", "cache-pause-wait": "1",
                        "http-header-fields": "x-api-key: " + self.job.stream_key if progressive and self.job.stream_key else "",
                        "demuxer-lavf-format": "mov" if progressive else "",
                        "demuxer-lavf-o": "decryption_key=" + self.job.source.options()["decryption_key"]
                            if progressive and self.job.source.options() else ""}
            for key, value in per_file.items():
                player.command("set", key, value)
            with self.guard:
                self.data.update(hwdecSelection=selected_hwdec, hwdecCacheHit=cache_hit,
                                 engineReused=reused, engineId=resources.get("id") if resources else None,
                                 engineInitializeMs=(time.monotonic()-initial)*1000)
            player.command("loadfile", media_uri)
            message = W.MSG()
            while not self.stop.is_set() and not self.job.cancelled.is_set() and user.IsWindow(self.parent):
                while user.PeekMessageW(C.byref(message), None, 0, 0, 1):
                    user.TranslateMessage(C.byref(message))
                    user.DispatchMessageW(C.byref(message))
                for _ in range(64):
                    event = player.dll.mpv_wait_event(player.handle, 0).contents
                    if event.id == 0:
                        break
                    if event.id == 21:  # MPV_EVENT_PLAYBACK_RESTART: first frame has restarted.
                        frame_ready = True
                    if event.id == 7 and event.data:
                        fields = C.cast(event.data, C.POINTER(C.c_int))
                        if fields[0] == 4 or fields[1] < 0:
                            if progressive and self.job.source.network_failed.is_set():
                                raise SourceReadError("Native media input unavailable")
                            if fields[1] in (-14, -15):  # mpv AO/VO initialization errors
                                raise NativeOutputError("Native audio/video output unavailable")
                            retry_software()
                for _ in range(64):
                    try:
                        revision, command = self.commands.get_nowait()
                    except queue.Empty:
                        break
                    if "rect" in command:
                        x, y, width, height = command["rect"]
                        client = W.RECT()
                        if not user.GetClientRect(self.parent, C.byref(client)):
                            raise RuntimeError("Desktop parent unavailable")
                        width, height = min(width, max(1, client.right - x)), min(height, max(1, client.bottom - y))
                        user.SetWindowPos(hwnd, W.HWND(0), x, y, width, height, 0x0010)
                    if "visible" in command:
                        user.ShowWindow(hwnd, 4 if command["visible"] else 0)
                    for key, option in (("paused", "pause"), ("rate", "speed"), ("volume", "volume"), ("muted", "mute")):
                        if key in command:
                            value = command[key]
                            desired[key] = value
                            player.command("set", option, "yes" if value is True else "no" if value is False else value * 100 if key == "volume" else value)
                            grace = time.monotonic() + 3
                    if "seek" in command:
                        target = command["seek"]
                        if self.job.duration and target >= self.job.duration:
                            target = max(0, self.job.duration - .05)
                        player.command("seek", target, "absolute+exact")
                        requested_position = target
                        frame_ready = False
                        initial = time.monotonic()
                        grace = initial + 3
                    with self.guard:
                        self.data["revision"] = revision
                if progressive and self.job.source.network_failed.is_set():
                    raise SourceReadError("Native media input unavailable")
                now = time.monotonic()
                width = int(player.number("video-params/w"))
                height = int(player.number("video-params/h"))
                # A decoded first frame/output is required, not merely a
                # hardware capability string or successful loadfile command.
                hwdec = player.get("hwdec-current")
                position = player.number("time-pos", self.job.start_seconds)
                paused = player.get("pause") == "yes"
                seeking = player.get("seeking") == "yes"
                eof = player.get("eof-reached") == "yes"
                video_ready = (frame_ready and width > 0 and height > 0
                    and player.get("current-vo") == "gpu"
                    and player.get("video-out-params") is not None)
                audio_ready = audio_output_ready(description, player)
                input_ready = bool(self.input_hooks)
                if video_ready and not input_ready:
                    # The input bridge is an output concern, not a hwdec test.
                    input_ready = self.forward_input(hwnd)
                output_ready = video_ready and audio_ready and input_ready
                if video_ready and hwdec and hwdec != observed_hwdec:
                    if preferences and self.host.hardware and not retried:
                        if hwdec != "no":
                            preferences.remember(description, hwdec)
                        else:
                            preferences.forget(description)
                    if hwdec == "no" and self.host.hardware and not retried:
                        fallback_reason = ("mpv-software-fallback" if observed_hwdec or cache_hit
                                           else "hardware-unavailable")
                    observed_hwdec = hwdec
                if eof and not seeking and not output_ready:
                    if video_ready:
                        raise NativeOutputError("Native audio/input output unavailable")
                    retry_software(no_frame=True, reason="no-first-frame")
                    continue
                avsync = player.number("avsync")
                buffering = progressive and (player.get("paused-for-cache") == "yes"
                                             or not output_ready and self.job.source.reading.is_set())
                buffer_start, buffer_end = 0.0, self.job.duration or 0.0
                if progressive:
                    buffer_start = position
                    buffer_end = max(position, player.number("demuxer-cache-time", position))
                    try:
                        ranges = json.loads(player.get("demuxer-cache-state") or "{}").get("seekable-ranges", [])
                        selected = next((r for r in ranges if r["start"] - .5 <= position <= r["end"] + .5), None)
                        if selected:
                            buffer_start, buffer_end = max(0, selected["start"]), selected["end"]
                    except (ValueError, TypeError, KeyError):
                        pass
                if last_position is None or abs(position - last_position) > .01 or paused or seeking:
                    last_position, last_progress = position, now
                unstable = not paused and not buffering and not seeking and not eof and now > grace
                frame_drops=player.number("frame-drop-count")
                decoder_drops=player.number("decoder-frame-drop-count")
                dropping=drop_watch.observe(now,frame_drops,decoder_drops,
                    player.number("container-fps",30),desired["rate"],unstable)
                if buffering:
                    last_progress = now
                if unstable and abs(avsync) > .2:
                    slow_since = slow_since or now
                else:
                    slow_since = None
                # mpv handles hardware decode errors and tries software itself.
                # VO drops / A-V lag alone cannot identify a broken hw decoder.
                # Retain a bounded watchdog for genuinely missing/stalled video,
                # and the final H264 fallback for sustained software overload.
                software_slow = hwdec == "no" and (dropping or slow_since and now - slow_since > 2)
                stalled = unstable and now - last_progress > 3
                missing_frame = not video_ready and not buffering and now - initial > 10
                if (unstable and software_slow) or stalled or missing_frame:
                    if progressive and self.job.source.network_failed.is_set():
                        raise SourceReadError("Native media input timed out")
                    retry_software(reason="no-first-frame" if missing_frame else "playback-stalled" if stalled else "software-overload")
                    continue
                if not output_ready and video_ready and not buffering and now - initial > 10:
                    raise NativeOutputError("Native audio/input output unavailable")
                with self.guard:
                    self.data.update(state="ended" if eof and not seeking and output_ready else "buffering" if buffering else "ready" if output_ready else "preparing",
                                     time=position, duration=player.number("duration", self.job.duration),
                                     paused=paused, rate=player.number("speed", desired["rate"]),
                                     volume=player.number("volume", desired["volume"] * 100) / 100,
                                     muted=player.get("mute") == "yes", seeking=seeking,
                                     width=width, height=height, decoder="software" if hwdec == "no" else "hardware" if hwdec else "probing",
                                     hwdec=hwdec, hwdecSelection=selected_hwdec, hwdecCacheHit=cache_hit,
                                     hardwareFallbackReason=fallback_reason,
                                     videoOutputReady=video_ready, audioOutputReady=audio_ready, inputReady=input_ready,
                                     avsync=avsync, audioDevice=player.get("audio-device"),
                                     buffering=buffering, outputReady=output_ready, bufferStart=buffer_start,
                                     bufferEnd=min(buffer_end, self.job.duration or buffer_end),
                                     audioExclusive=player.get("audio-exclusive"), audioOutput=player.get("current-ao"),
                                     frameDrops=frame_drops, decoderDrops=decoder_drops)
                self.stop.wait(.04)
        except NativeOutputError:
            with self.guard:
                self.data.update(state="failed", failureCode="native-output")
        except SourceReadError:
            with self.guard:
                self.data.update(state="failed", failureCode="source-read")
        except Exception:
            with self.guard:
                self.data.update(state="failed", failureCode="native-decode")
        finally:
            for surface, (previous, callback) in self.input_hooks.items():
                if user.IsWindow(surface):
                    user.SetWindowLongPtrW(surface, -4, previous)
            self.input_hooks.clear()
            reusable = self.engine_resources is not None and self.data.get("state") != "failed"
            try:
                if reusable and player:
                    user.ShowWindow(hwnd, 0)
                    player.command("set", "pause", "yes")
                    player.command("set", "mute", "yes")
                    player.command("stop")
                    deadline = time.monotonic()+2
                    while player.get("idle-active") != "yes":
                        if time.monotonic() >= deadline:
                            raise RuntimeError("Native input did not stop")
                        self.host._pump_engine()
                        time.sleep(.01)
                    for key in ("http-header-fields", "demuxer-lavf-o", "demuxer-lavf-format"):
                        player.command("set", key, "")
                    # Drain EOF/restart events from the old file before a new
                    # session can interpret them as its own first-frame ACK.
                    for _ in range(1024):
                        if player.dll.mpv_wait_event(player.handle, 0).contents.id == 0:
                            break
                    else:
                        raise RuntimeError("Native event queue did not settle")
            except Exception:
                reusable = False
            if not reusable:
                try:
                    if player:
                        player.close()
                finally:
                    if hwnd and user.IsWindow(hwnd):
                        user.DestroyWindow(hwnd)
                    if self.engine_resources is not None:
                        self.engine_resources.clear()
