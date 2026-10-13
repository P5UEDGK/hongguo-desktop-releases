"""Decoder selection and recovery regressions without a physical GPU fault."""
import ctypes as C
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from desktop_native import DecoderPreferences, FrameDropWatch, NativeSession, Event


def description(**changes):
    video = dict(contentType='video/mp4; codecs="hvc1.1.6.L186"',
                 pixelFormat='yuv420p', width=1920, height=1080)
    video.update(changes)
    return {'video': video, 'audio': []}


class PolicyTests(unittest.TestCase):
    def test_display_loss_never_means_decoder_loss(self):
        watch = FrameDropWatch()
        self.assertFalse(any(watch.observe(n/10, n*4, 0, 30, 2, True) for n in range(40)))
        watch = FrameDropWatch()
        self.assertTrue(any(watch.observe(n/10, 0, n*4, 30, 2, True) for n in range(40)))

    def test_cache_requires_known_format_and_actual_hardware_result(self):
        cache = DecoderPreferences()
        for mode in (None, 'no', 'auto', 'auto-safe'):
            cache.remember(description(), mode)
        cache.remember({'video': {'contentType': 'hevc'}}, 'dxva2-copy')
        self.assertEqual(cache.select(description()), ('auto-safe', False))
        cache.remember(description(), 'dxva2-copy')
        self.assertEqual(cache.select(description()), ('dxva2-copy', True))
        self.assertEqual(cache.select(description(), False), ('no', False))
        for changes in ({'contentType': 'video/mp4; codecs="hvc1.2.4.L186"'},
                        {'pixelFormat': 'yuv420p10le'}, {'width': 1280}, {'height': 720}):
            self.assertEqual(cache.select(description(**changes)), ('auto-safe', False))
        cache.forget(description())
        self.assertEqual(cache.select(description()), ('auto-safe', False))
        self.assertEqual(DecoderPreferences().select(description()), ('auto-safe', False))

    def test_cache_is_bounded_and_thread_safe(self):
        cache = DecoderPreferences()
        def fill(offset):
            for n in range(80):
                cache.remember(description(width=100+offset+n), 'd3d11va')
                cache.select(description(width=100+offset+n))
        workers = [threading.Thread(target=fill, args=(i*100,)) for i in range(3)]
        for worker in workers: worker.start()
        for worker in workers: worker.join()
        self.assertEqual(len(cache.choices), 64)

    def run_session(self, *, cache=None, hardware=True, mode='d3d11va',
                    output_loss=False, avsync=0, stalled=False, first_frame=True,
                    audio=True, input_ready=True, error=None, auto_fallback=False,
                    network_failure=False):
        clock = SimpleNamespace(now=0.0)
        class Stop:
            stopped = False
            def is_set(self): return self.stopped
            def set(self): self.stopped = True
            def wait(self, seconds):
                clock.now += seconds
                if clock.now > 23: self.set()
        driver = SimpleNamespace(events=[], holds=[])
        def wait_event(*_):
            return C.pointer(driver.events.pop(0) if driver.events else Event(0, 0, 0, None))
        driver.mpv_initialize = lambda *_: 0
        driver.mpv_wait_event = wait_event
        players = []
        class Player:
            def __init__(self, dll):
                self.dll, self.handle = dll, 1
                self.options, self.commands, self.loads = {}, [], 0
                players.append(self)
            def check(self, _): pass
            def option(self, key, value): self.options[key] = value
            def command(self, *args):
                self.commands.append(args)
                if args[0] == 'set': self.options[args[1]] = args[2]
                if args[0] == 'loadfile':
                    self.loads += 1
                    if first_frame: driver.events.append(Event(21, 0, 0, None))
                    if error and self.loads == 1:
                        fields = (C.c_int*2)(4, error)
                        driver.holds.append(fields)
                        driver.events.append(Event(7, 0, 0, C.cast(fields, C.c_void_p).value))
            def get(self, key):
                hwdec = ('no' if self.options.get('hwdec') == 'no' or
                         auto_fallback and clock.now > 2 else mode)
                return {'hwdec-current': hwdec, 'pause': self.options.get('pause'),
                        'current-vo': 'gpu', 'video-out-params': 'frame',
                        'current-ao': 'wasapi' if audio else None,
                        'audio-params': 'decoded' if audio else None,
                        'audio-device': 'auto', 'audio-exclusive': 'no'}.get(key)
            def number(self, key, default=0):
                return {'time-pos': 12.5 if stalled else 12.5+clock.now*2,
                        'video-params/w': 1920, 'video-params/h': 1080,
                        'frame-drop-count': clock.now*40 if output_loss else 0,
                        'decoder-frame-drop-count': 0, 'avsync': avsync,
                        'container-fps': 30, 'duration': 87,
                        'speed': self.options.get('speed', 1)}.get(key, default)
            def close(self): self.handle = None
        user = SimpleNamespace(SetThreadDpiAwarenessContext=lambda *_: None,
            CreateWindowExW=lambda *_: 1, IsWindow=lambda *_: True,
            IsWindowVisible=lambda *_: False, PeekMessageW=lambda *_: False,
            GetClientRect=lambda *_: True, MapWindowPoints=lambda *_: 0,
            SetWindowRgn=lambda *_: True, DestroyWindow=lambda *_: None)
        cache = cache or DecoderPreferences()
        host = SimpleNamespace(user=user, dll=driver, hardware=hardware, decode_preferences=cache)
        desc = description()
        if not audio: desc['audio'] = [{}]
        job = SimpleNamespace(start_seconds=0, source=Path('synthetic.mp4'), duration=87,
                              cancelled=threading.Event(), source_description=desc)
        session = NativeSession(host, job, 1)
        session.stop = Stop()
        session.forward_input = lambda _: input_ready
        session.submit({'paused': False, 'rate': 2, 'volume': .4, 'muted': True})
        with patch('desktop_native.Mpv', Player), patch('desktop_native.time.monotonic', lambda: clock.now):
            session.run()
        return session.snapshot(), players[0], cache

    def test_moving_hardware_video_with_display_drops_and_av_lag_is_not_reloaded(self):
        state, player, _ = self.run_session(output_loss=True, avsync=.3)
        self.assertEqual(state['state'], 'ready')
        self.assertEqual(player.loads, 1)
        self.assertFalse(state['softwareRetried'])
        self.assertEqual(player.options['hwdec-software-fallback'], '3')

    def test_next_same_format_reuses_verified_method_and_forced_software_wins(self):
        first, _, cache = self.run_session(mode='dxva2-copy')
        second, player, _ = self.run_session(cache=cache, mode='dxva2-copy')
        self.assertFalse(first['hwdecCacheHit'])
        self.assertTrue(second['hwdecCacheHit'])
        self.assertIn(('set', 'hwdec', 'dxva2-copy'), player.commands)
        soft, player, _ = self.run_session(cache=cache, hardware=False)
        self.assertEqual(soft['decoder'], 'software')
        self.assertFalse(soft['hwdecCacheHit'])

    def test_mpv_automatic_fallback_does_not_reload_and_invalidates_cached_choice(self):
        cache = DecoderPreferences()
        cache.remember(description(), 'd3d11va')
        state, player, _ = self.run_session(cache=cache, auto_fallback=True)
        self.assertEqual(player.loads, 1)
        self.assertEqual(state['decoder'], 'software')
        self.assertEqual(state['hardwareFallbackReason'], 'mpv-software-fallback')
        self.assertEqual(cache.select(description()), ('auto-safe', False))

    def test_real_stall_and_missing_frame_have_bounded_software_retry(self):
        for conditions in ({'stalled': True}, {'first_frame': False}):
            with self.subTest(conditions=conditions):
                state, player, _ = self.run_session(**conditions)
                self.assertEqual(player.loads, 2)
                self.assertEqual(state['failureCode'], 'native-decode')
                self.assertTrue(state['softwareRetried'])
                self.assertEqual(player.commands.count(('set', 'hwdec', 'no')), 1)
                for command in (('set', 'speed', 2), ('set', 'pause', 'no'),
                                ('set', 'volume', 40.0), ('set', 'mute', 'yes')):
                    self.assertIn(command, player.commands)

    def test_audio_and_input_failure_do_not_retry_software(self):
        for conditions in ({'audio': False}, {'input_ready': False}, {'error': -14}, {'error': -15}):
            with self.subTest(conditions=conditions):
                state, player, _ = self.run_session(**conditions)
                self.assertEqual(player.loads, 1)
                self.assertFalse(state['softwareRetried'])
                self.assertEqual(state['failureCode'], 'native-output')

    def test_sustained_software_lag_still_allows_final_fallback(self):
        state, player, _ = self.run_session(hardware=False, avsync=.3)
        self.assertEqual(state['failureCode'], 'native-decode')
        self.assertEqual(player.loads, 1)


if __name__ == '__main__': unittest.main()
