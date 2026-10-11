"""Standby ownership and cold-source regressions against the real session owner."""
from pathlib import Path
import tempfile
import asyncio
import queue
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from desktop_hls_service import HlsJobs, make_router
from desktop_native import NativeHost
from desktop_prefetch import EpisodePrefetcher

def eventually(predicate):
    until=time.monotonic()+2
    while not predicate() and time.monotonic()<until:time.sleep(.005)
    if not predicate():raise AssertionError('asynchronous metadata did not finish')

class StandbyTests(unittest.TestCase):
    def test_expired_activation_does_not_replace_newer_generation_or_clear_parent(self):
        prefetch=EpisodePrefetcher(lambda _:None,lambda _:({},[]),self.root/'cache',encoder=lambda *_:None)
        self.addCleanup(prefetch.close)
        jobs,_=self.jobs();jobs.on_start=prefetch.begin;jobs.on_activate=prefetch.promote
        parent=jobs.create('1234567890123456',1)
        child=jobs.create(parent.series_id,2,negotiate_codec=True,prewarm_parent=parent.id)
        child.video_mode='copy';child.source=self.root/'prepared.mp4'
        newer=jobs.create(parent.series_id,3)
        generation=prefetch.generation
        with self.assertRaises(HTTPException) as error:jobs.activate(child)
        self.assertEqual(error.exception.status_code,409)
        self.assertEqual(child.prewarm_parent,parent.id)
        self.assertEqual(prefetch.generation,generation)
        self.assertEqual(prefetch.current['episode'],3)
        prefetch.before_work(newer)
        self.assertEqual(prefetch.busy,newer.id)

    def test_child_control_failure_restores_queued_parent_intent(self):
        host=object.__new__(NativeHost);host.guard=threading.RLock()
        calls=[];data={"paused":False,"revision":0}
        def submit(body):
            calls.append(body);data.update(body,revision=len(calls));return len(calls)
        old=SimpleNamespace(job=SimpleNamespace(prewarm_parent=None),snapshot=lambda:dict(data),
            desired_state=lambda:{"paused":True},submit=submit)
        def rejected(_):raise queue.Full()
        child=SimpleNamespace(job=SimpleNamespace(prewarm_parent="old"),stop=threading.Event(),
            snapshot=lambda:{"outputReady":True},submit=rejected)
        host.sessions={"old":old,"child":child}
        with self.assertRaises(queue.Full):host.control("child",{"visible":True,"paused":False})
        self.assertEqual(calls,[{"paused":True},{"paused":True}])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def jobs(self):
        calls=[]
        jobs=HlsJobs(self.root,lambda *args:self.root/'cold.mp4',on_start=lambda *args:calls.append(args))
        # Keep source work deterministic while exercising create/ownership.
        jobs._run=lambda *args:None
        self.addCleanup(lambda:[jobs.release(k) for k in list(jobs.jobs)])
        return jobs,calls

    def test_stale_child_cannot_join_new_foreground_generation(self):
        from desktop_hls import EncodingCancelled
        prefetch=EpisodePrefetcher(lambda _:None,lambda _:({},[]),self.root/'cache',encoder=lambda *_:None)
        self.addCleanup(prefetch.close)
        jobs,_=self.jobs();jobs.on_start=prefetch.begin
        parent=jobs.create('1234567890123456',1)
        child=jobs.create(parent.series_id,2,negotiate_codec=True,prewarm_parent=parent.id)
        self.assertEqual(child.prefetch_generation,parent.prefetch_generation)
        next_job=SimpleNamespace(id='f'*32,cancelled=threading.Event(),failed=False)
        prefetch.begin(next_job,parent.series_id,9)
        with self.assertRaises(EncodingCancelled):prefetch.before_work(child)
        self.assertNotIn(child.id,prefetch.foreground);self.assertIsNone(prefetch.busy)

    def test_cancel_before_promoted_metadata_releases_finished_ownership(self):
        prefetch=EpisodePrefetcher(lambda _:None,lambda _:({},[]),self.root/'cache',encoder=lambda *_:None)
        self.addCleanup(prefetch.close)
        for mode in ('native','h264'):
            job=SimpleNamespace(id=mode,source=None,cancelled=threading.Event(),failed=False,video_mode=mode,
                                _prefetch_work_finished=True)
            with patch('desktop_prefetch.threading.Thread') as thread:
                prefetch.promote(job,'1234567890123456',2)
                args=thread.call_args.kwargs['args']
            prefetch.busy=job.id;job.cancelled.set();prefetch._load_promoted(*args)
            self.assertNotIn(job.id,prefetch.foreground);self.assertIsNone(prefetch.busy)

    def test_out_of_order_control_return_never_lowers_activation_revision(self):
        jobs,_=self.jobs();parent=jobs.create('1234567890123456',1)
        child=jobs.create(parent.series_id,2,negotiate_codec=True,prewarm_parent=parent.id)
        child.video_mode='native';child.ready.set()
        revisions=iter((10,9));state=dict(visible=True,outputReady=True,revision=9)
        jobs.native=SimpleNamespace(available=True,control=lambda *_:next(revisions),snapshot=lambda _:state,release=lambda _:None)
        control=next(route.endpoint for route in make_router(jobs,lambda _:True).routes if route.path.endswith('/control'))
        async def body():return {'visible':True,'paused':False,'muted':False}
        asyncio.run(control(child.id,SimpleNamespace(json=body)))
        asyncio.run(control(child.id,SimpleNamespace(json=body)))
        self.assertEqual(child.activation_revision,10)
        with self.assertRaises(HTTPException):jobs.activate(child)
        state['revision']=10;jobs.activate(child)

    def test_standby_bound_to_immediate_next_and_single_parent(self):
        jobs,calls=self.jobs()
        parent=jobs.create('1234567890123456',1)
        child=jobs.create(parent.series_id,2,negotiate_codec=True,prewarm_parent=parent.id)
        self.assertEqual(len(calls),1,'prewarm must not reset foreground prefetch')
        for series,ep in [(parent.series_id,3),('1234567890123457',2)]:
            with self.assertRaises(HTTPException):
                jobs.create(series,ep,negotiate_codec=True,prewarm_parent=parent.id)
        with self.assertRaises(HTTPException):
            jobs.create(parent.series_id,2,negotiate_codec=True,prewarm_parent=parent.id)
        with self.assertRaises(HTTPException):
            jobs.create(parent.series_id,3,negotiate_codec=True,prewarm_parent=child.id)
        jobs.release(parent.id)
        self.assertTrue(child.cancelled.is_set())

    def test_promoted_standby_survives_old_parent_release(self):
        jobs,calls=self.jobs()
        parent=jobs.create('1234567890123456',1)
        child=jobs.create(parent.series_id,2,negotiate_codec=True,prewarm_parent=parent.id)
        jobs.activate(child)
        jobs.release(parent.id)
        self.assertFalse(child.cancelled.is_set())
        self.assertIsNone(child.prewarm_parent)

    def test_failed_or_cancelled_activation_never_acknowledges_success(self):
        jobs,_=self.jobs();parent=jobs.create('1234567890123456',1)
        child=jobs.create(parent.series_id,2,negotiate_codec=True,prewarm_parent=parent.id)
        child.failed=True
        with self.assertRaises(HTTPException) as failed:jobs.activate(child)
        self.assertEqual(failed.exception.status_code,409);self.assertEqual(child.prewarm_parent,parent.id)
        child.failed=False;child.cancelled.set()
        with self.assertRaises(HTTPException) as cancelled:jobs.activate(child)
        self.assertEqual(cancelled.exception.status_code,404)

    def test_late_metadata_cannot_rewind_a_new_foreground_generation(self):
        prefetch=EpisodePrefetcher(lambda _:None,lambda _:({},[]),self.root/'cache',encoder=lambda *_:None)
        self.addCleanup(prefetch.close)
        job=SimpleNamespace(id='a'*32,source=None,cancelled=threading.Event(),failed=False,video_mode='native')
        with patch('desktop_prefetch.threading.Thread') as thread:
            prefetch.promote(job,'1234567890123456',2)
            target=thread.call_args.kwargs['target'];args=thread.call_args.kwargs['args']
        self.assertEqual(prefetch.current['episode'],2,'generation moves before metadata runs')
        next_job=SimpleNamespace(id='b'*32,cancelled=threading.Event(),failed=False)
        prefetch.begin(next_job,'1234567890123457',7);generation=prefetch.generation
        target(*args)
        self.assertEqual(prefetch.generation,generation)
        self.assertEqual(prefetch.current,{'seriesId':'1234567890123457','episode':7})
        self.assertIn(next_job.id,prefetch.foreground)
        self.assertNotIn(job.id,prefetch.foreground,'superseded metadata releases only its old ownership')

    def test_superseded_metadata_does_not_release_unfinished_encoder(self):
        prefetch=EpisodePrefetcher(lambda _:None,lambda _:({},[]),self.root/'cache',encoder=lambda *_:None)
        self.addCleanup(prefetch.close)
        old=SimpleNamespace(id='old',video_mode='h264',source=None,cancelled=threading.Event(),failed=False)
        generation=prefetch.begin(old,'1234567890123456',1);prefetch.busy=old.id
        new=SimpleNamespace(id='new',cancelled=threading.Event(),failed=False)
        prefetch.begin(new,'1234567890123456',3)
        prefetch._load_promoted(old,'1234567890123456',1,generation)
        self.assertEqual(prefetch.busy,old.id)
        self.assertIn(old.id,prefetch.foreground)
        prefetch.finish(old,'1234567890123456',1,None)
        self.assertIsNone(prefetch.busy)
        self.assertNotIn(old.id,prefetch.foreground)

    def test_warm_encoding_uses_existing_gate_and_does_not_advance_generation(self):
        prefetch=EpisodePrefetcher(lambda _:None,lambda _:({},[]),self.root/'cache',encoder=lambda *args:None)
        self.addCleanup(prefetch.close)
        parent=SimpleNamespace(id='a'*32,cancelled=threading.Event(),failed=False)
        prefetch.begin(parent,'1234567890123456',1)
        prefetch.foreground.clear()
        warm=SimpleNamespace(id='b'*32,cancelled=threading.Event(),failed=False,prewarm_parent=parent.id,prefetch_generation=prefetch.generation)
        generation=prefetch.generation
        prefetch.before_work(warm)
        self.assertEqual(prefetch.busy,warm.id)
        prefetch.finish(warm,'1234567890123456',2,None)
        self.assertEqual(prefetch.generation,generation)
        self.assertEqual(prefetch.current['episode'],1)
        self.assertFalse(prefetch.foreground)
        self.assertIsNone(prefetch.busy)

    def test_native_control_keeps_parent_until_applied_activation(self):
        jobs,_=self.jobs()
        parent=jobs.create('1234567890123456',1)
        child=jobs.create(parent.series_id,2,negotiate_codec=True,prewarm_parent=parent.id)
        child.video_mode='native';child.ready.set()
        state={'visible':False,'outputReady':True,'revision':0}
        jobs.native=SimpleNamespace(available=True,snapshot=lambda _:state,
            control=lambda *_:9,release=lambda _:None)
        routes=make_router(jobs,lambda _:True).routes
        control=next(route.endpoint for route in routes if route.path.endswith('/control'))
        async def body():return {'visible':True,'paused':False,'muted':False}
        result=asyncio.run(control(child.id,SimpleNamespace(json=body)))
        self.assertEqual(result,{'revision':9})
        self.assertEqual(child.prewarm_parent,parent.id)
        activate=next(route.endpoint for route in routes if route.path.endswith('/activate'))
        for update in ({'visible':False,'outputReady':True,'revision':9},
                       {'visible':True,'outputReady':False,'revision':9},
                       {'visible':True,'outputReady':True,'revision':8}):
            state.update(update)
            with self.assertRaises(HTTPException):activate(child.id)
            self.assertEqual(child.prewarm_parent,parent.id)
        state.update(visible=True,outputReady=True,revision=9)
        self.assertEqual(activate(child.id),{'activated':True})
        jobs.release(parent.id)
        self.assertFalse(child.cancelled.is_set())

    def test_parent_cancel_before_native_ack_cancels_queued_child(self):
        jobs,_=self.jobs()
        parent=jobs.create('1234567890123456',1)
        child=jobs.create(parent.series_id,2,negotiate_codec=True,prewarm_parent=parent.id)
        child.video_mode='native';child.activation_revision=9
        jobs.native=SimpleNamespace(snapshot=lambda _:dict(visible=False,outputReady=True,revision=8),release=lambda _:None)
        with self.assertRaises(HTTPException):jobs.activate(child)
        jobs.release(parent.id)
        self.assertTrue(child.cancelled.is_set())

    def test_activation_cancel_does_not_clear_parent_download_queue(self):
        prefetch=EpisodePrefetcher(lambda _:None,lambda _:({},[]),self.root/'cache',encoder=lambda *_:None)
        self.addCleanup(prefetch.close)
        parent=SimpleNamespace(id='a'*32,cancelled=threading.Event(),failed=False)
        prefetch.begin(parent,'1234567890123456',1);prefetch.foreground.clear()
        child=SimpleNamespace(id='b'*32,cancelled=threading.Event(),failed=False,prewarm_parent=parent.id,prefetch_generation=prefetch.generation)
        prefetch.before_work(child)
        expected=[(prefetch.generation,9,'1234567890123456')]
        prefetch.download_pending=expected.copy()
        child.prewarm_parent=None;child.cancelled.set()
        prefetch.promote(child,'1234567890123456',2)
        prefetch.finish(child,'1234567890123456',2,None)
        self.assertEqual(prefetch.download_pending,expected)
        self.assertEqual(prefetch.current['episode'],1)
        self.assertIsNone(prefetch.busy)

    def test_child_submit_failure_rolls_back_previous_pause(self):
        host=object.__new__(NativeHost);host.guard=threading.RLock()
        parent_state={'paused':False,'revision':0};commands=[]
        def submit_parent(body):
            commands.append(body);parent_state.update(body,revision=parent_state['revision']+1)
            return parent_state['revision']
        def submit_child(body):raise queue.Full()
        parent=SimpleNamespace(stop=threading.Event(),snapshot=lambda:parent_state.copy(),submit=submit_parent)
        child=SimpleNamespace(stop=threading.Event(),snapshot=lambda:{'outputReady':True},
            submit=submit_child,job=SimpleNamespace(prewarm_parent='a'*32))
        host.sessions={'a'*32:parent,'b'*32:child}
        with self.assertRaises(queue.Full):host.control('b'*32,{'visible':True,'paused':False,'muted':False})
        self.assertEqual(commands,[{'paused':True},{'paused':False}])
        self.assertFalse(parent_state['paused'])

    def test_finishing_between_activation_and_promotion_keeps_old_metadata(self):
        source=self.root/'prepared.mp4';source.write_bytes(b'prepared')
        prefetch=EpisodePrefetcher(lambda _:source,lambda _:({},[]),self.root/'cache',encoder=lambda *_:None)
        self.addCleanup(prefetch.close)
        parent=SimpleNamespace(id='a'*32,cancelled=threading.Event(),failed=False)
        prefetch.begin(parent,'1234567890123456',1)
        prefetch.foreground.clear()
        warm=SimpleNamespace(id='b'*32,cancelled=threading.Event(),failed=False,prewarm_parent=parent.id,prefetch_generation=prefetch.generation)
        prefetch.before_work(warm)
        warm.prewarm_parent=None
        prefetch.finish(warm,'1234567890123456',2,source)
        self.assertEqual(prefetch.current['episode'],1)
        self.assertIsNone(prefetch.current_source)
        self.assertFalse(prefetch.current_complete)
        self.assertFalse(prefetch.foreground)

    def test_native_standby_does_not_close_foreground_and_refuses_sound(self):
        class Session:
            def __init__(self,host,job,parent):
                self.job=job;self.stop=threading.Event();self.closed=False
                self.data={'outputReady':False,'paused':True,'revision':0}
                self.thread=SimpleNamespace(start=lambda:None)
            def close(self):self.closed=True;self.stop.set()
            def snapshot(self):return self.data
            def submit(self,body):self.data.update(body,revision=self.data['revision']+1);return self.data['revision']
        host=object.__new__(NativeHost);host.available=True;host.guard=threading.RLock();host.sessions={}
        host.parent_window=lambda:1
        parent=SimpleNamespace(id='a'*32,cancelled=threading.Event(),prewarm_parent=None)
        child=SimpleNamespace(id='b'*32,cancelled=threading.Event(),prewarm_parent=parent.id)
        with patch('desktop_native.NativeSession',Session):
            host.prepare(parent);old=host.sessions[parent.id]
            host.prepare(child);warm=host.sessions[child.id]
            self.assertFalse(old.closed)
            self.assertEqual(len(host.sessions),2)
            for body in ({'paused':False},{'muted':False},{'visible':True}):
                with self.assertRaises(ValueError):host.control(child.id,body)
            warm.data['outputReady']=True
            host.control(child.id,{'visible':True,'paused':False,'muted':False,'rate':3})
            self.assertTrue(old.data['paused'])
            self.assertFalse(warm.data['paused'])
            self.assertEqual(warm.data['rate'],3)
            host.release(parent.id);host.release(child.id)
            self.assertFalse(host.sessions)

    def test_promotion_reuses_stream_identity_without_opening_another_source(self):
        source=self.root/'existing.mp4';source.write_bytes(b'prepared')
        def unexpected(*_):raise AssertionError('must reuse the already playing source')
        prefetch=EpisodePrefetcher(unexpected,lambda _:({},[{'index':2,'vid':'1234567890123456'}]),
                                  self.root/'cache',encoder=unexpected)
        self.addCleanup(prefetch.close)
        job=SimpleNamespace(id='a'*32,source=source,cancelled=threading.Event(),failed=False,video_mode='native')
        prefetch.promote(job,'1234567890123456',2)
        self.assertTrue(prefetch.wait_idle(2))
        self.assertIs(prefetch.current_source,source)
        self.assertEqual(prefetch.current['episode'],2)
        self.assertTrue(prefetch.snapshot()['currentSourceComplete'])
        self.assertFalse(prefetch.foreground)

    def test_hls_promotion_keeps_encoding_slot_until_worker_finishes(self):
        source=self.root/'existing.mp4';source.write_bytes(b'prepared')
        prefetch=EpisodePrefetcher(lambda _:source,lambda _:({},[{'index':2,'vid':'1234567890123456'}]),
                                  self.root/'cache',encoder=lambda *_:None)
        self.addCleanup(prefetch.close)
        prefetch.cache.contains=lambda *_,**kw:True
        job=SimpleNamespace(id='a'*32,source=source,cancelled=threading.Event(),failed=False,
                            video_mode='h264',prewarm_parent='b'*32,prefetch_generation=prefetch.generation)
        prefetch.before_work(job)
        job.prewarm_parent=None
        prefetch.promote(job,'1234567890123456',2)
        eventually(lambda:prefetch.current_source is source)
        self.assertEqual(prefetch.busy,job.id)
        self.assertIn(job.id,prefetch.foreground)
        self.assertFalse(prefetch.pending)
        prefetch.finish(job,'1234567890123456',2,source)
        self.assertIsNone(prefetch.busy)
        self.assertFalse(prefetch.foreground)
        self.assertTrue(prefetch.current_complete)
        # Completion may also precede activation (a cache hit or fast encoder).
        prefetch.promote(job,'1234567890123456',2)
        self.assertTrue(prefetch.wait_idle(2))
        self.assertFalse(prefetch.foreground)
        self.assertTrue(prefetch.current_complete)

    def test_promotion_metadata_failure_releases_finished_job(self):
        def unavailable(_):raise OSError('owned metadata failure')
        prefetch=EpisodePrefetcher(lambda _:None,unavailable,self.root/'cache',encoder=lambda *_:None)
        self.addCleanup(prefetch.close)
        prefetch._report=lambda:self.assertFalse(prefetch.condition._is_owned(),
            'diagnostic report lock must not be acquired while holding scheduler condition')
        job=SimpleNamespace(id='a'*32,source=self.root/'ready.mp4',cancelled=threading.Event(),
                            failed=False,video_mode='native')
        prefetch.promote(job,'1234567890123456',2)
        self.assertTrue(prefetch.wait_idle(2))
        self.assertFalse(prefetch.foreground)
        self.assertFalse(prefetch.pending)


if __name__=='__main__':unittest.main()
