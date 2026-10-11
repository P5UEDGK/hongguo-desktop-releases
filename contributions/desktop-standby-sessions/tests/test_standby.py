"""Standby ownership and cold-source regressions against the real session owner."""
from pathlib import Path
import tempfile
import asyncio
import queue
import threading
import time
from contextlib import nullcontext
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
    def test_standby_claims_queued_and_inflight_download_before_fallback(self):
        vid='123456780002'
        for kind in ('queued-encode','queued-download','inflight-download'):
            with self.subTest(kind=kind):
                loaded=[];entered=threading.Event();release=threading.Event();source=SimpleNamespace(close=lambda:None)
                def fallback(_):loaded.append('fallback');return source
                def download(_):entered.set();release.wait(2);loaded.append('download');return source
                prefetch=EpisodePrefetcher(fallback,lambda _:({},[{'index':2,'vid':vid}]),self.root/kind,encoder=lambda *_:None,download_loader=download,ahead=0)
                self.addCleanup(prefetch.close);prefetch.generation=1;prefetch.pending=[(1,2,vid,'h264')]
                if kind!='queued-encode':prefetch.download_pending=[(1,2,vid)]
                if kind=='inflight-download':
                    prefetch.downloader=threading.Thread(target=prefetch._download,daemon=True);prefetch.downloader.start();self.assertTrue(entered.wait(1))
                job=SimpleNamespace(id='warm',prewarm_parent='parent',prefetch_generation=1,cancelled=threading.Event());returned=[]
                worker=threading.Thread(target=lambda:returned.append(prefetch.load_standby_source(job,'series',2)));worker.start()
                if kind=='inflight-download':
                    eventually(lambda:not prefetch.pending);self.assertEqual(returned,[]);self.assertEqual(loaded,[]);release.set()
                worker.join(2);self.assertFalse(worker.is_alive());self.assertEqual(returned,[source])
                self.assertEqual(prefetch.pending,[]);self.assertEqual(prefetch.download_pending,[]);self.assertNotIn(vid,prefetch.sources)
                self.assertEqual(loaded,['download'] if kind=='inflight-download' else ['fallback']);prefetch.close()

    def test_activation_rejects_parent_pause_ownership_changed_after_child_control(self):
        jobs,_=self.jobs();parent=jobs.create('1234567890123456',1);parent.video_mode='native'
        child=jobs.create(parent.series_id,2,negotiate_codec=True,prewarm_parent=parent.id);child.video_mode='native';child.activation_revision=1
        host=object.__new__(NativeHost);host.guard=threading.RLock();state={'paused':False,'revision':0}
        def submit(body):
            state.update(body,revision=state['revision']+1)
            if 'paused' in body:previous.pause_revision=state['revision']
            return state['revision']
        previous=SimpleNamespace(job=parent,stop=threading.Event(),snapshot=lambda:dict(state),desired_state=lambda:dict(state),submit=submit)
        session=SimpleNamespace(job=child,stop=threading.Event(),snapshot=lambda:{'visible':True,'outputReady':True,'revision':1},submit=lambda _:1)
        host.sessions={parent.id:previous,child.id:session};jobs.native=host
        try:
            host.control(child.id,{'visible':True,'paused':False});host.control(parent.id,{'paused':False})
            with self.assertRaises(HTTPException) as error:jobs.activate(child)
            self.assertEqual(error.exception.status_code,409);self.assertEqual(child.prewarm_parent,parent.id);self.assertTrue(session.handoff_previous)
            host.control(child.id,{'visible':True,'paused':False});jobs.activate(child)
            self.assertTrue(state['paused']);self.assertIsNone(child.prewarm_parent);self.assertEqual(session.handoff_previous,[])
        finally:jobs.native=None

    def test_duplicate_creation_token_does_not_revoke_existing_standby(self):
        import uuid
        jobs,_=self.jobs();token=f'{int((time.time()+30)*1000):013d}-{uuid.uuid4().hex}'
        parent=jobs.create('1234567890123456',1,request_token=token)
        child=jobs.create(parent.series_id,2,negotiate_codec=True,prewarm_parent=parent.id)
        with self.assertRaises(HTTPException) as error:jobs.create(parent.series_id,1,request_token=token)
        self.assertEqual(error.exception.status_code,409);self.assertIn(child.id,jobs.jobs);self.assertFalse(child.cancelled.is_set())

    def test_retained_standby_membership_blocks_foreground_creation(self):
        jobs,_=self.jobs();parent=jobs.create('1234567890123456',1)
        child=jobs.create(parent.series_id,2,negotiate_codec=True,prewarm_parent=parent.id)
        release=jobs.release;jobs.release=lambda identifier:None
        try:
            with self.assertRaises(HTTPException) as error:jobs.create(parent.series_id,3)
            self.assertEqual(error.exception.status_code,503);self.assertIn(child.id,jobs.jobs)
        finally:jobs.release=release

    def test_stale_parent_create_does_not_block_current_standby(self):
        jobs,_=self.jobs();generation=[0]
        def begin(job,*_):generation[0]+=1;job.prefetch_generation=generation[0]
        jobs.on_start=begin
        old=jobs.create('1234567890123456',1);current=jobs.create(old.series_id,1)
        with self.assertRaises(HTTPException) as error:jobs.create(old.series_id,2,negotiate_codec=True,prewarm_parent=old.id)
        self.assertEqual(error.exception.status_code,409);self.assertEqual(set(jobs.jobs),{old.id,current.id})
        child=jobs.create(current.series_id,2,negotiate_codec=True,prewarm_parent=current.id);self.assertEqual(child.prewarm_parent,current.id)

    def test_cancel_during_promoted_metadata_never_commits_source_or_queue(self):
        source=self.root/'promoted-source.mp4';source.write_bytes(b'owned')
        job=SimpleNamespace(id='a'*32,cancelled=threading.Event(),failed=False,video_mode='h264',source=source)
        def metadata(_):job.cancelled.set();return {},[{'index':2,'vid':'123456780002'},{'index':3,'vid':'123456780003'}]
        prefetch=EpisodePrefetcher(lambda _:source,metadata,self.root/'promoted-cancel',encoder=lambda *_:None);self.addCleanup(prefetch.close)
        prefetch.begin(job,'1234567890123456',2);prefetch._load_promoted(job,'1234567890123456',2,prefetch.generation)
        self.assertIsNone(prefetch.current_source);self.assertEqual(prefetch.download_pending,[]);self.assertEqual(prefetch.sources,{})


    def test_queued_hide_invalidates_old_visible_activation(self):
        jobs,_=self.jobs();parent=jobs.create('1234567890123456',1);parent.video_mode='native'
        child=jobs.create(parent.series_id,2,negotiate_codec=True,prewarm_parent=parent.id);child.video_mode='native';child.ready.set();child.activation_revision=1
        jobs.native=SimpleNamespace(available=True,control=lambda *_:2,snapshot=lambda _:{'visible':True,'outputReady':True,'revision':1},release=lambda _:None)
        endpoint=next(route.endpoint for route in make_router(jobs,lambda _:True).routes if route.path.endswith('/control'))
        async def body():return {'visible':False,'paused':True}
        asyncio.run(endpoint(child.id,SimpleNamespace(json=body)))
        with self.assertRaises(HTTPException) as error:jobs.activate(child)
        self.assertEqual(error.exception.status_code,409);self.assertEqual(child.prewarm_parent,parent.id)

    def test_cancelled_pending_parent_cannot_create_standby(self):
        jobs,_=self.jobs();parent=jobs.create('1234567890123456',1)
        jobs.native=SimpleNamespace(release=lambda _:False);jobs.release(parent.id)
        self.assertIn(parent.id,jobs.jobs)
        with self.assertRaises(HTTPException) as error:jobs.create(parent.series_id,2,negotiate_codec=True,prewarm_parent=parent.id)
        self.assertEqual(error.exception.status_code,404);self.assertEqual(set(jobs.jobs),{parent.id})
        jobs.native=None


    def test_activation_commit_releases_parent_session_ownership(self):
        jobs,_=self.jobs();parent=jobs.create('1234567890123456',1);parent.video_mode='native'
        child=jobs.create(parent.series_id,2,negotiate_codec=True,prewarm_parent=parent.id);child.video_mode='native';child.activation_revision=1
        host=object.__new__(NativeHost);host.guard=threading.RLock()
        previous=SimpleNamespace(pause_revision=1,snapshot=lambda:{'paused':True,'revision':1})
        session=SimpleNamespace(handoff_previous=[(previous,False,1)],snapshot=lambda:{'visible':True,'outputReady':True,'revision':1})
        host.sessions={parent.id:previous,child.id:session};jobs.native=host
        try:
            jobs.activate(child);self.assertEqual(session.handoff_previous,[]);self.assertIsNone(child.prewarm_parent)
        finally:jobs.native=None

    def test_control_rejects_non_object_json_with_400(self):
        jobs,_=self.jobs();job=jobs.create('1234567890123456',1)
        endpoint=next(route.endpoint for route in make_router(jobs,lambda _:True).routes if route.path.endswith('/control'))
        for value in (None,[],42,'text'):
            async def body():return value
            with self.assertRaises(HTTPException) as error:asyncio.run(endpoint(job.id,SimpleNamespace(json=body)))
            self.assertEqual(error.exception.status_code,400)

    def test_promotion_callback_failure_does_not_detach_parent(self):
        jobs,_=self.jobs();parent=jobs.create('1234567890123456',1);parent.video_mode='h264'
        child=jobs.create(parent.series_id,2,negotiate_codec=True,prewarm_parent=parent.id);child.video_mode='h264'
        def failed(*_):raise RuntimeError('promotion failed')
        jobs.on_activate=failed
        with self.assertRaisesRegex(RuntimeError,'promotion failed'):jobs.activate(child)
        self.assertEqual(child.prewarm_parent,parent.id)

    def test_control_ack_wait_does_not_block_async_event_loop(self):
        jobs,_=self.jobs();job=jobs.create('1234567890123456',1);job.video_mode='native';job.ready.set()
        entered=threading.Event();release=threading.Event()
        def blocking(*_):entered.set();release.wait(1);return 1
        jobs.native=SimpleNamespace(available=True,control=blocking,release=lambda _:None)
        endpoint=next(route.endpoint for route in make_router(jobs,lambda _:True).routes if route.path.endswith('/control'))
        async def body():return {'visible':False,'paused':True}
        async def exercise():
            task=asyncio.create_task(endpoint(job.id,SimpleNamespace(json=body)))
            try:
                for _ in range(200):
                    if entered.is_set() or task.done():break
                    await asyncio.sleep(.005)
                self.assertTrue(entered.is_set(),'control worker must enter the native call')
                self.assertFalse(task.done(),'event loop must stay schedulable during native ACK wait')
            finally:release.set();await task
        asyncio.run(exercise())

    def test_repeated_visible_handoff_keeps_pause_ownership_and_latest_intent(self):
        for later in (None, True, False):
            for reject in (False, True):
                with self.subTest(later=later, reject=reject):
                    host=object.__new__(NativeHost);host.guard=threading.RLock();state={'paused':False,'revision':0};pauses=[]
                    def submit(body):
                        state.update(body,revision=state['revision']+1)
                        if 'paused' in body:parent.pause_revision=state['revision'];pauses.append(body['paused'])
                        return state['revision']
                    parent=SimpleNamespace(job=SimpleNamespace(prewarm_parent=None),stop=threading.Event(),snapshot=lambda:dict(state),desired_state=lambda:dict(state),submit=submit)
                    child=SimpleNamespace(job=SimpleNamespace(prewarm_parent='parent'),stop=threading.Event(),snapshot=lambda:{'outputReady':True},submit=lambda _:1,close=lambda:True)
                    host.sessions={'parent':parent,'child':child};host.control('child',{'visible':True,'paused':False})
                    if later is not None:host.control('parent',{'paused':later})
                    if reject:
                        def rejected(_):raise ValueError('child rejected')
                        child.submit=rejected
                        with self.assertRaises(ValueError):host.control('child',{'visible':True,'paused':False})
                    else:host.control('child',{'visible':True,'paused':False})
                    if later is None:self.assertEqual(pauses,[True], 'owned pause must not be submitted twice')
                    host.release('child');self.assertEqual(state['paused'],later if later is not None else False)

    def test_cancelled_handoff_preserves_later_parent_pause_intent(self):
        host=object.__new__(NativeHost);host.guard=threading.RLock();state={'paused':False,'revision':0}
        def submit(body):
            state.update(body,revision=state['revision']+1)
            if 'paused' in body:parent.pause_revision=state['revision']
            return state['revision']
        parent=SimpleNamespace(job=SimpleNamespace(prewarm_parent=None),stop=threading.Event(),snapshot=lambda:dict(state),desired_state=lambda:dict(state),submit=submit)
        child=SimpleNamespace(job=SimpleNamespace(prewarm_parent='parent'),stop=threading.Event(),snapshot=lambda:{'outputReady':True},submit=lambda _:1,close=lambda:True)
        host.sessions={'parent':parent,'child':child};host.control('child',{'visible':True,'paused':False})
        host.control('parent',{'paused':True});host.release('child');self.assertTrue(state['paused'])

    def test_generation_advance_revokes_completed_pending_native_handoff_and_restores_parent(self):
        jobs,_=self.jobs();generation=[0];observed=[]
        def begin(job,*_):
            generation[0]+=1;job.prefetch_generation=generation[0]
            if generation[0]>1:observed.append((child.cancelled.is_set(),child_session.stop.is_set(),parent_state['paused']))
        jobs.on_start=begin
        parent=jobs.create('1234567890123456',1);parent.video_mode='native'
        child=jobs.create(parent.series_id,2,negotiate_codec=True,prewarm_parent=parent.id);child.video_mode='native';child.done.set();child.ready.set()
        host=object.__new__(NativeHost);host.guard=threading.RLock();parent_state={'paused':False,'revision':0};pending=[]
        def parent_submit(body):parent_state.update(body,revision=parent_state['revision']+1);return parent_state['revision']
        parent_session=SimpleNamespace(job=parent,stop=threading.Event(),desired_state=lambda:dict(parent_state),snapshot=lambda:dict(parent_state),submit=parent_submit,close=lambda:True)
        def close_child():child_session.stop.set();pending.clear();return True
        def child_submit(body):pending.append(body);return len(pending)
        child_session=SimpleNamespace(job=child,stop=threading.Event(),snapshot=lambda:{'outputReady':True},submit=child_submit,close=close_child)
        host.sessions={parent.id:parent_session,child.id:child_session};jobs.native=host
        host.control(child.id,{'visible':True,'paused':False,'muted':False});self.assertTrue(parent_state['paused']);self.assertTrue(pending)
        jobs.create(parent.series_id,3)
        self.assertEqual(observed,[(True,True,False)],'revocation and parent rollback must precede the new generation')
        self.assertEqual(pending,[]);self.assertNotIn(child.id,host.sessions)

    def test_native_parent_cannot_activate_an_hls_standby(self):
        jobs,_=self.jobs();parent=jobs.create('1234567890123456',1);parent.video_mode='native'
        child=jobs.create(parent.series_id,2,negotiate_codec=True,prewarm_parent=parent.id);child.video_mode='h264'
        with self.assertRaises(HTTPException) as error:jobs.activate(child)
        self.assertEqual(error.exception.status_code,409);self.assertEqual(child.prewarm_parent,parent.id)

    def wired_jobs(self, encoder):
        source=self.root/'cold-fixture.mp4';source.write_bytes(b'owned test bytes')
        metadata=[{'index':i,'vid':str(123456780000+i)} for i in (1,2,3)]
        prefetch=EpisodePrefetcher(lambda _:source,lambda _:({},metadata),self.root/'cache',encoder=encoder,ahead=0)
        self.addCleanup(prefetch.close);prefetch.cache.contains=lambda *_,**kw:True
        jobs=HlsJobs(self.root,source_loader=prefetch.load_source,standby_source_loader=prefetch.load_standby_source,
            encoder=encoder,on_start=prefetch.begin,before_work=prefetch.before_work,on_finish=prefetch.finish,
            on_activate=prefetch.promote,negotiation_seconds=.01)
        self.addCleanup(jobs.close)
        self.enterContext(patch('desktop_hls_service.open_media',side_effect=lambda *_,**kw:nullcontext(SimpleNamespace(duration=10000000))))
        self.enterContext(patch('desktop_hls_service.describe_streams',return_value={'copyEligible':True}))
        return jobs,prefetch

    def test_prefetched_source_waits_for_background_owner_then_transfers(self):
        closed=[];source=SimpleNamespace(close=lambda:closed.append(True));vid='123456780002'
        job=SimpleNamespace(id='warm',prewarm_parent='parent',prefetch_generation=1,cancelled=threading.Event())
        prefetch=EpisodePrefetcher(lambda _:self.fail('must reuse transferred source'),lambda _:({},[{'index':2,'vid':vid}]),self.root/'transfer',encoder=lambda *_:None)
        prefetch.generation=1;prefetch.sources[vid]=source;prefetch.active=(1,2,vid,'h264');prefetch.pending=[(1,2,vid,'h264')]
        returned=[];thread=threading.Thread(target=lambda:returned.append(prefetch.load_standby_source(job,'series',2)));thread.start()
        self.assertTrue(prefetch.background_cancelled.wait(1));self.assertFalse(returned);self.assertFalse(closed)
        with prefetch.condition:prefetch.active=None;prefetch.condition.notify_all()
        thread.join(2);self.assertFalse(thread.is_alive());self.assertEqual(returned,[source]);self.assertNotIn(vid,prefetch.sources);self.assertFalse(prefetch.pending)
        source.close();self.assertEqual(closed,[True]);prefetch.close()

    def test_stale_cold_or_transferred_source_is_closed(self):
        from desktop_hls import EncodingCancelled
        for borrowed in (False,True):
            with self.subTest(borrowed=borrowed):
                closed=[];source=SimpleNamespace(close=lambda:closed.append(True))
                job=SimpleNamespace(id='warm',prewarm_parent='parent',prefetch_generation=1,cancelled=threading.Event())
                def load(_):prefetch.generation=2;return source
                prefetch=EpisodePrefetcher(load,lambda _:({},[{'index':2,'vid':'123456780002'}]),
                    self.root/('borrowed' if borrowed else 'new'),encoder=lambda *_:None)
                prefetch.generation=1
                if borrowed:
                    class Sources(dict):
                        def get(self,key):return source
                        def pop(self,key,default=None):prefetch.generation=2;return source
                    prefetch.sources=Sources()
                try:
                    with self.assertRaises(EncodingCancelled):prefetch.load_standby_source(job,'series',2)
                    self.assertEqual(closed,[True])
                finally:prefetch.close()

    def test_cold_standby_loads_without_becoming_current_episode(self):
        def encode(source,directory,on_ready,**kwargs):
            directory.mkdir(exist_ok=True);(directory/'complete.marker').write_text('complete');on_ready()
        jobs,prefetch=self.wired_jobs(encode)
        parent=jobs.create('1234567890123456',1);self.assertTrue(parent.done.wait(2));self.assertFalse(parent.failed)
        child=jobs.create(parent.series_id,2,negotiate_codec=True,prewarm_parent=parent.id)
        self.assertTrue(child.done.wait(2));self.assertFalse(child.failed,child.failure_code)
        self.assertTrue(child.ready.is_set());self.assertIsNotNone(child.source)
        self.assertEqual(prefetch.current,{'seriesId':parent.series_id,'episode':1})
        self.assertEqual(prefetch.generation,parent.prefetch_generation)

    def test_new_generation_cancels_running_warm_encoder_before_foreground_work(self):
        entered=threading.Event();cancelled=threading.Event();encodes=[]
        def encode(source,directory,on_ready,**kwargs):
            encodes.append(directory.name)
            if len(encodes)==2:
                from desktop_hls import EncodingCancelled
                entered.set()
                until=time.monotonic()+2
                while not kwargs['cancelled']() and time.monotonic()<until:time.sleep(.005)
                if not kwargs['cancelled']():raise AssertionError('stale warm encode was not cancelled')
                cancelled.set();raise EncodingCancelled()
            directory.mkdir(exist_ok=True);(directory/'complete.marker').write_text('complete');on_ready()
        jobs,prefetch=self.wired_jobs(encode)
        parent=jobs.create('1234567890123456',1);self.assertTrue(parent.done.wait(2))
        child=jobs.create(parent.series_id,2,negotiate_codec=True,prewarm_parent=parent.id)
        self.assertTrue(entered.wait(2));self.assertEqual(prefetch.busy,child.id)
        with self.assertRaises(HTTPException) as error:jobs.create(parent.series_id,3)
        self.assertEqual(error.exception.status_code,503)
        self.assertTrue(cancelled.wait(1));self.assertTrue(child.done.wait(1))
        newer=jobs.create(parent.series_id,3)
        self.assertTrue(child.cancelled.is_set())
        self.assertTrue(newer.done.wait(2));self.assertFalse(newer.failed,newer.failure_code)
        self.assertEqual(encodes,[parent.id,child.id,newer.id])

    def test_standby_metadata_generation_change_never_loads_source(self):
        from desktop_hls import EncodingCancelled
        calls=[];job=SimpleNamespace(id='warm',prewarm_parent='parent',prefetch_generation=1,cancelled=threading.Event())
        def metadata(_):
            prefetch.begin(SimpleNamespace(id='new'),'1234567890123456',3)
            return {},[{'index':2,'vid':'123456780002'}]
        prefetch=EpisodePrefetcher(lambda vid:calls.append(vid),metadata,self.root/'cache',encoder=lambda *_:None)
        self.addCleanup(prefetch.close);prefetch.generation=1
        with self.assertRaises(EncodingCancelled):prefetch.load_standby_source(job,'1234567890123456',2)
        self.assertEqual(calls,[])

    def test_stale_completed_standby_is_rejected_before_visible_control(self):
        jobs,_=self.jobs();parent=jobs.create('1234567890123456',1)
        child=jobs.create(parent.series_id,2,negotiate_codec=True,prewarm_parent=parent.id)
        child.video_mode='native';child.ready.set();child.prefetch_generation=1;jobs.foreground_generation=2
        jobs.native=SimpleNamespace(available=True,control=lambda *_:self.fail('stale control must not reach parent/child'),release=lambda _:None)
        control=next(route.endpoint for route in make_router(jobs,lambda _:True).routes if route.path.endswith('/control'))
        async def body():return {'visible':True,'paused':False}
        with self.assertRaises(HTTPException) as result:asyncio.run(control(child.id,SimpleNamespace(json=body)))
        self.assertEqual(result.exception.status_code,409);self.assertIsNone(child.activation_revision)

    def test_native_prewarm_rejects_unacknowledged_hls_parent(self):
        host=NativeHost(dll_path=Path('missing-owned-fixture.dll'));host.available=True
        job=SimpleNamespace(id='child',prewarm_parent='hls-parent',native_parent=123,cancelled=threading.Event())
        with patch.object(host,'parent_window',return_value=123),patch('desktop_native.NativeSession') as session:
            with self.assertRaises(RuntimeError):host.prepare(job)
            session.assert_not_called()
        self.assertEqual(host.sessions,{});self.assertEqual(host.preparing,set())

    def test_control_submit_and_revision_are_atomic_against_delete(self):
        jobs,_=self.jobs();parent=jobs.create('1234567890123456',1)
        child=jobs.create(parent.series_id,2,negotiate_codec=True,prewarm_parent=parent.id)
        child.video_mode='native';child.ready.set()
        entered=threading.Event();leave=threading.Event();delete_attempt=threading.Event();deleted=threading.Event()
        outcome=[];failures=[]
        def submit(*_):
            entered.set()
            if not leave.wait(2):raise AssertionError('test did not release submit')
            return 7
        jobs.native=SimpleNamespace(available=True,control=submit,release=lambda _:None)
        control=next(route.endpoint for route in make_router(jobs,lambda _:True).routes if route.path.endswith('/control'))
        async def body():return {'visible':True,'paused':False}
        def request():
            try:outcome.append(asyncio.run(control(child.id,SimpleNamespace(json=body))))
            except Exception as e:failures.append(e)
        def delete():
            delete_attempt.set();jobs.release(child.id);deleted.set()
        sender=threading.Thread(target=request);deleter=threading.Thread(target=delete)
        sender.start();self.assertTrue(entered.wait(2));deleter.start()
        try:
            self.assertTrue(delete_attempt.wait(2))
            self.assertFalse(deleted.wait(.15),'DELETE must not cancel an in-flight accepted native control')
            self.assertFalse(child.cancelled.is_set())
        finally:
            leave.set();sender.join(3);deleter.join(3)
        self.assertFalse(sender.is_alive());self.assertFalse(deleter.is_alive())
        self.assertEqual(failures,[]);self.assertEqual(outcome,[{'revision':7}])
        self.assertEqual(child.activation_revision,7);self.assertTrue(deleted.is_set())

    def test_prepare_standby_retains_parent_and_uses_bound_requesting_window(self):
        host=NativeHost(dll_path=Path('missing-owned-fixture.dll'));host.available=True
        old=SimpleNamespace(close=lambda:self.fail('standby preparation must retain the active parent'))
        host.sessions={'parent':old}
        job=SimpleNamespace(id='child',prewarm_parent='parent',native_parent=123,cancelled=threading.Event())
        with patch.object(host,'parent_window',return_value=123) as parent,patch('desktop_native.NativeSession') as session:
            host.prepare(job)
            parent.assert_called_once_with(job)
            session.assert_called_once_with(host,job,123)
            session.return_value.thread.start.assert_called_once()
        self.assertIs(host.sessions['parent'],old)
        self.assertEqual(set(host.sessions),{'parent','child'})
        self.assertEqual(host.preparing,set())

    def test_fast_metadata_starts_after_parent_detach_and_finishes_bookkeeping(self):
        observed=[]
        source=self.root/'prepared.mp4';source.write_bytes(b'prepared')
        def metadata(_):
            observed.append(child.prewarm_parent)
            return {},[{'index':2,'vid':'1234567890123456'}]
        prefetch=EpisodePrefetcher(lambda _:source,metadata,self.root/'cache',encoder=lambda *_:None)
        self.addCleanup(prefetch.close)
        prefetch.cache.contains=lambda *_,**kw:True
        jobs,_=self.jobs();jobs.on_start=prefetch.begin;jobs.on_activate=prefetch.promote
        parent=jobs.create('1234567890123456',1);prefetch.foreground.clear()
        child=jobs.create(parent.series_id,2,negotiate_codec=True,prewarm_parent=parent.id)
        child.video_mode='copy';child.source=source;child._prefetch_work_finished=True
        with patch('desktop_prefetch.threading.Thread') as thread:
            thread.return_value.start.side_effect=lambda:thread.call_args.kwargs['target'](*thread.call_args.kwargs['args'])
            jobs.activate(child)
        self.assertEqual(observed,[None],'even an immediate metadata daemon must see detached ownership')
        self.assertTrue(prefetch.current_complete)
        self.assertNotIn(child.id,prefetch.foreground)

    def test_expired_activation_does_not_replace_newer_generation_or_clear_parent(self):
        prefetch=EpisodePrefetcher(lambda _:None,lambda _:({},[]),self.root/'cache',encoder=lambda *_:None)
        self.addCleanup(prefetch.close)
        jobs,_=self.jobs();jobs.on_start=prefetch.begin;jobs.on_activate=prefetch.promote
        parent=jobs.create('1234567890123456',1)
        child=jobs.create(parent.series_id,2,negotiate_codec=True,prewarm_parent=parent.id)
        child.video_mode='copy';child.source=self.root/'prepared.mp4';child.done.set()
        newer=jobs.create(parent.series_id,3)
        generation=prefetch.generation
        with self.assertRaises(HTTPException) as error:jobs.activate(child)
        self.assertEqual(error.exception.status_code,404)
        self.assertTrue(child.cancelled.is_set(),'ordinary create revokes stale standby before advancing the generation')
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
                prefetch.promote(job,'1234567890123456',2)()
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
        job=SimpleNamespace(id='a'*32,source=None,directory=self.root/'old-directory',cancelled=threading.Event(),failed=False,video_mode='native')
        with patch('desktop_prefetch.threading.Thread') as thread:
            prefetch.promote(job,'1234567890123456',2)()
            target=thread.call_args.kwargs['target'];args=thread.call_args.kwargs['args']
        self.assertEqual(prefetch.current['episode'],2,'generation moves before metadata runs')
        next_job=SimpleNamespace(id='b'*32,cancelled=threading.Event(),failed=False)
        prefetch.begin(next_job,'1234567890123457',7);generation=prefetch.generation
        target(*args)
        self.assertEqual(prefetch.generation,generation)
        self.assertEqual(prefetch.current,{'seriesId':'1234567890123457','episode':7})
        self.assertIn(next_job.id,prefetch.foreground)
        self.assertNotIn(job.id,prefetch.foreground,'superseded metadata releases only its old ownership')
        self.assertNotIn(job.id,prefetch.foreground_directories,'superseded metadata releases its completed directory')

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
        host=NativeHost(dll_path=Path('missing-owned-fixture.dll'));host.available=True
        host.parent_window=lambda job=None:1
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
        prefetch.promote(job,'1234567890123456',2)()
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
        prefetch.promote(job,'1234567890123456',2)()
        eventually(lambda:prefetch.current_source is source)
        self.assertEqual(prefetch.busy,job.id)
        self.assertIn(job.id,prefetch.foreground)
        self.assertFalse(prefetch.pending)
        prefetch.finish(job,'1234567890123456',2,source)
        self.assertIsNone(prefetch.busy)
        self.assertFalse(prefetch.foreground)
        self.assertTrue(prefetch.current_complete)
        # Completion may also precede activation (a cache hit or fast encoder).
        prefetch.promote(job,'1234567890123456',2)()
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
        prefetch.promote(job,'1234567890123456',2)()
        self.assertTrue(prefetch.wait_idle(2))
        self.assertFalse(prefetch.foreground)
        self.assertFalse(prefetch.pending)


if __name__=='__main__':unittest.main()
