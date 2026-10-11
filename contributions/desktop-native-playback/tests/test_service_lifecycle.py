"""Native admission and autonomous session ownership regressions."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import time
import unittest

import av
from fastapi import HTTPException
from desktop_hls_service import HlsJobs, make_router


def eventually(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('condition did not become true')


class LifecycleTests(unittest.TestCase):
    def test_creation_cancellation_covers_lost_response_and_early_delete(self):
        import uuid
        jobs=self.jobs();jobs._run=lambda job,*_:job.done.set()
        for _ in range(8):
            token=f'{int((time.time()+30)*1000):013d}-{uuid.uuid4().hex}'
            job=jobs.create('1234567890123456',1,request_token=token)
            self.assertTrue(job.done.wait(1));self.assertEqual(job.id,token[14:])
            self.assertIsNot(jobs.cancel_request(token),False);self.assertNotIn(job.id,jobs.jobs)
            self.assertIsNot(jobs.cancel_request(token),False)
            with self.assertRaises(HTTPException) as error:jobs.create('1234567890123456',1,request_token=token)
            self.assertEqual(error.exception.status_code,409)
        early=f'{int((time.time()+30)*1000):013d}-{uuid.uuid4().hex}';jobs.cancel_request(early)
        with self.assertRaises(HTTPException):jobs.create('1234567890123456',1,request_token=early)
        self.assertFalse(jobs.jobs)

    def test_creation_tokens_validate_expiry_and_bound_cancellation_state(self):
        import uuid
        jobs=self.jobs();jobs._run=lambda job,*_:job.done.set()
        for token in ('invalid',f'{int((time.time()+120)*1000):013d}-{uuid.uuid4().hex}',f'{int((time.time()-1)*1000):013d}-{uuid.uuid4().hex}'):
            with self.assertRaises(HTTPException):jobs.create('1234567890123456',1,request_token=token)
        ordinary=jobs.create('1234567890123456',1);self.assertTrue(ordinary.done.wait(1))
        for _ in range(1030):jobs.cancel_request(f'{int((time.time()+30)*1000):013d}-{uuid.uuid4().hex}')
        self.assertLessEqual(len(jobs.cancelled_requests),1024);self.assertIn(ordinary.id,jobs.jobs)
        with self.assertRaises(HTTPException):jobs.create('1234567890123456',1,request_token=f'{int((time.time()+30)*1000):013d}-{uuid.uuid4().hex}')

    def test_creation_cancel_endpoint_is_idempotent_and_authenticated(self):
        import uuid
        from starlette.requests import Request
        jobs=self.jobs();router=make_router(jobs,lambda key:key=='owned')
        cancel=next(route.endpoint for route in router.routes if route.path.endswith('/requests/{token}'))
        prepare=next(route.endpoint for route in router.routes if route.path=='/desktop/hls')
        token=f'{int((time.time()+30)*1000):013d}-{uuid.uuid4().hex}'
        self.assertEqual(cancel(token).status_code,204)
        request=Request({'type':'http','query_string':b'series_id=1234567890123456&ep=1','headers':[(b'x-api-key',b'owned')],'server':('127.0.0.1',1234)})
        router.dependencies[0].dependency(request)
        with self.assertRaises(HTTPException) as error:prepare(request,'1234567890123456',1,request_token=token)
        self.assertEqual(error.exception.status_code,409)
        with self.assertRaises(HTTPException):cancel('bad')
        with self.assertRaises(HTTPException) as error:router.dependencies[0].dependency(Request({'type':'http','headers':[]}))
        self.assertEqual(error.exception.status_code,401)

    def test_resumed_complete_cache_has_zero_origin_without_reencoding(self):
        from desktop_playable_cache import PlayableEpisodeCache
        from desktop_hls import encode_hls
        cache=PlayableEpisodeCache(self.root/'full-cache',encoder=encode_hls)
        jobs=self.jobs(encoder=cache.encode)
        first=jobs.create('1234567890123456',1)
        self.assertTrue(first.done.wait(5));self.assertFalse(first.failed,first.failure_code)
        cache.encoder=lambda *a,**kw:self.fail('a cached resumed episode must not reencode')
        resumed=jobs.create('1234567890123456',1,start_seconds=.8)
        self.assertTrue(resumed.done.wait(3));self.assertFalse(resumed.failed,resumed.failure_code)
        self.assertTrue(resumed.ready.is_set());self.assertEqual(resumed.window_origin,0)
        with av.open(str(resumed.directory/'index.m3u8')) as media:
            self.assertGreater(sum(1 for _ in media.decode(video=0)),0)

    def test_shutdown_keeps_reaping_until_pending_native_release_finishes(self):
        stopped=threading.Event()
        native=SimpleNamespace(release=lambda _:stopped.is_set())
        jobs=self.jobs(native=native,idle_seconds=.05);jobs._run=lambda *_:None
        job=jobs.create('1234567890123456',1);job.done.set();job.directory.mkdir()
        (job.directory/'owned').write_bytes(b'owned')
        self.assertFalse(jobs.close());self.assertIn(job.id,jobs.jobs)
        stopped.set();eventually(lambda:not jobs.jobs)
        eventually(lambda:jobs.reaper is None)
        self.assertFalse(job.directory.exists())

    def test_delete_reports_pending_until_native_teardown_and_preserves_output(self):
        native=SimpleNamespace(release=lambda _:False)
        jobs=self.jobs(native=native)
        jobs._run=lambda *_:None
        job=jobs.create('1234567890123456',1)
        job.directory.mkdir();(job.directory/'owned').write_bytes(b'owned');job.done.set()
        delete=next(r.endpoint for r in make_router(jobs,lambda _:True).routes if r.path.endswith('/{identifier}') and 'DELETE' in r.methods)
        self.assertEqual(delete(job.id).status_code,202)
        self.assertIn(job.id,jobs.jobs);self.assertTrue(job.directory.exists())
        native.release=lambda _:True
        self.assertEqual(delete(job.id).status_code,204)
        self.assertNotIn(job.id,jobs.jobs);self.assertFalse(job.directory.exists())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'owned.mp4'
        with av.open(str(self.source), 'w') as output:
            video = output.add_stream('libx264', rate=10)
            video.width = video.height = 64
            video.pix_fmt = 'yuv420p'
            for i in range(20):
                frame = av.VideoFrame(64, 64, 'yuv420p')
                frame.pts = i
                for plane in frame.planes:
                    plane.update(bytes(plane.buffer_size))
                for packet in video.encode(frame): output.mux(packet)
            for packet in video.encode(): output.mux(packet)

    def jobs(self, **kwargs):
        jobs = HlsJobs(self.root, lambda *_: self.source, **kwargs)
        self.addCleanup(lambda: jobs.close() if hasattr(jobs, 'close') else
                        [jobs.release(key) for key in list(jobs.jobs)])
        return jobs

    def test_native_admitted_while_encoder_busy_and_total_bound_retained(self):
        encoding = threading.Event()
        unblock = threading.Event()
        prepared = threading.Event()
        def encode(source, target, ready, **kwargs):
            encoding.set()
            unblock.wait(3)
        self.addCleanup(unblock.set)
        native = SimpleNamespace(prepare=lambda _: prepared.set(), release=lambda _: None)
        jobs = self.jobs(encoder=encode, native=native, max_workers=1, max_jobs=2)
        first = jobs.create('1234567890123456', 1)
        self.assertTrue(encoding.wait(2))
        second = jobs.create('1234567890123456', 2, negotiate_codec=True)
        eventually(lambda: second.source_description is not None)
        with jobs.guard:
            second.video_mode = 'native'
            second.mode_selected.set()
        self.assertTrue(prepared.wait(1), 'native waited for an encoder slot')
        self.assertTrue(second.done.wait(1))
        self.assertFalse(second.failed)
        with self.assertRaises(HTTPException) as error:
            jobs.create('1234567890123456', 3)
        self.assertEqual(error.exception.status_code, 503)
        unblock.set()
        self.assertTrue(first.done.wait(2))

    def test_queued_hls_cancel_does_not_run_encoder_or_exceed_workers(self):
        entered = threading.Event()
        unblock = threading.Event()
        calls = []
        def encode(*args, **kwargs):
            calls.append(1)
            entered.set()
            unblock.wait(3)
        self.addCleanup(unblock.set)
        jobs = self.jobs(encoder=encode, max_workers=1)
        first = jobs.create('1234567890123456', 1)
        self.assertTrue(entered.wait(2))
        second = jobs.create('1234567890123456', 2)
        time.sleep(.15)
        self.assertEqual(len(calls), 1)
        jobs.release(second.id)
        self.assertTrue(second.done.wait(1))
        self.assertEqual(second.failure_code, 'cancelled')
        unblock.set()
        self.assertTrue(first.done.wait(2))
        self.assertEqual(len(calls), 1)

    def test_expiry_runs_without_new_requests_and_close_stops_reaper(self):
        releases = []
        native = SimpleNamespace(prepare=lambda job: job.directory.mkdir(), release=releases.append)
        jobs = self.jobs(native=native, idle_seconds=30)
        job = jobs.create('1234567890123456', 1, negotiate_codec=True)
        eventually(lambda: job.source_description is not None)
        with jobs.guard:
            job.video_mode = 'native'
            job.mode_selected.set()
        self.assertTrue(job.done.wait(1))
        (job.directory / 'partial').write_bytes(b'partial')
        with jobs.guard:
            jobs.idle_seconds = .25
            job.touched = time.monotonic() - 1
        eventually(lambda: job.id not in jobs.jobs)
        self.assertIn(job.id, releases)
        self.assertFalse(job.directory.exists())
        jobs.close()
        self.assertTrue(jobs.reaper is None or not jobs.reaper.is_alive())
        with self.assertRaises(HTTPException):
            jobs.create('1234567890123456', 2)
