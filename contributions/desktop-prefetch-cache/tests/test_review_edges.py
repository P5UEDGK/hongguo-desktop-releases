"""Regression cases from asynchronous upstream review; no real media or account."""
from pathlib import Path
import os
import json
import tempfile,threading,time,unittest,uuid
from unittest.mock import patch
from desktop_hls import EncodingCancelled
from desktop_prefetch import EpisodePrefetcher
from desktop_playable_cache import PlayableEpisodeCache
from job_fixture import Job
from test_prefetch import complete_output,encoder,PROFILE_FILES


class ReviewEdges(unittest.TestCase):
    def test_same_generation_retry_deduplicates_active_and_completed_future(self):
        from types import SimpleNamespace
        for loaded in (False,True):
            rows=[{'index':n,'vid':str(10000000+n)} for n in (1,2,3)]
            value=EpisodePrefetcher(lambda _:self.source,lambda _:({},rows),self.root/('retry-'+str(loaded)),encoder=encoder,profile_files=PROFILE_FILES,ahead=2)
            self.addCleanup(value.close);job=Job(uuid.uuid4().hex,self.root/('job-'+str(loaded)));value.begin(job,'series',1)
            value.downloader=SimpleNamespace(is_alive=lambda:True)
            job.source_loader('series',1)
            value.download_pending.pop(0)
            if loaded:value.sources['10000002']=self.source
            else:value.download_active=(value.generation,2,'10000002')
            rows[:]=[{'index':n,'vid':str(10000000+n)} for n in (1,2,4)]
            job.source_loader('series',1)
            self.assertEqual([task[2] for task in value.download_pending],['10000004'])
            self.assertEqual([vid for ep,vid in value.latest_episodes if ep>1],['10000002','10000004'])
            value.downloader=None

    def test_foreground_commit_preserves_artifact_but_propagates_cancellation(self):
        cache=self.cache();cancel=threading.Event();published=[]
        reserve=cache._reserve
        def commit(*args,**kwargs):
            reserve(*args,**kwargs);cancel.set();return True
        target=self.root/'cancelled-foreground'
        with patch.object(cache,'_reserve',side_effect=commit):
            with self.assertRaises(EncodingCancelled):cache.encode(self.source,target,cancelled=cancel.is_set,on_cache_key=published.append)
        self.assertEqual(published,[])
        self.assertTrue(cache.contains(self.source),'committed cache survives caller cancellation')

    def test_integration_worker_invokes_the_documented_job_bound_loader(self):
        import re,ast
        document=(Path(__file__).resolve().parents[1]/'INTEGRATION.md').read_text(encoding='utf8')
        snippets=re.findall(r'```python\n(.*?)```',document,re.S)
        statements=[node for code in snippets for node in ast.parse(code).body if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='source' for t in node.targets)]
        self.assertEqual(len(statements),1,'integration worker must explicitly call the job-bound loader')
        expression=compile(ast.Expression(statements[0].value),'<documented-worker-load>','eval')
        calls=[];prefetch=EpisodePrefetcher(lambda vid:(calls.append(vid),self.source)[1],lambda sid:(calls.append(sid),[{'index':1,'vid':'123456780001'}]),self.root/'documented-job',encoder=encoder,profile_files=PROFILE_FILES,ahead=0)
        self.addCleanup(prefetch.close);old=Job(uuid.uuid4().hex,self.root/'old-doc');new=Job(uuid.uuid4().hex,self.root/'new-doc');prefetch.begin(old,'series',1);prefetch.begin(new,'series',1)
        with self.assertRaises(EncodingCancelled):eval(expression,dict(job=old,series_id='series',episode=1,prefetch=prefetch))
        self.assertEqual(calls,[]);self.assertEqual(eval(expression,dict(job=new,series_id='series',episode=1,prefetch=prefetch)),self.source)


    def test_same_episode_restart_rejects_old_job_before_loaders(self):
        calls=[];prefetch=EpisodePrefetcher(lambda vid:(calls.append(vid),self.source)[1],lambda series:(calls.append(series),[{'index':1,'vid':'123456780001'}]),self.root/'same-episode',encoder=encoder,profile_files=PROFILE_FILES,ahead=0)
        self.addCleanup(prefetch.close);old=Job(uuid.uuid4().hex,self.root/'old');new=Job(uuid.uuid4().hex,self.root/'new')
        prefetch.begin(old,'series',1);prefetch.begin(new,'series',1)
        with self.assertRaises(EncodingCancelled):getattr(old,'source_loader',prefetch.load_source)('series',1)
        self.assertEqual(calls,[]);self.assertIsNone(prefetch.current_source)
        self.assertEqual(new.source_loader('series',1),self.source);self.assertEqual(calls,['series','123456780001'])

    def test_complete_cache_rejects_low_latency_part_uri_family(self):
        path=self.output/'index.m3u8';original=path.read_text(encoding='utf8')
        for tag in ('#EXT-X-PART:DURATION=1,URI="part0.m4s"','#EXT-X-PRELOAD-HINT:TYPE=PART,URI="part1.m4s"','#EXT-X-RENDITION-REPORT:URI="other.m3u8",LAST-MSN=1'):
            with self.subTest(tag=tag):
                path.write_text(original.replace('#EXTM3U\n','#EXTM3U\n'+tag+'\n',1),encoding='utf8')
                with self.assertRaises(ValueError):self.cache().store(self.source,self.output)

    def test_load_source_rejects_obsolete_or_closed_before_metadata(self):
        for closed in (False,True):
            calls=[];prefetch=EpisodePrefetcher(lambda _:None,lambda series:(calls.append(series),[{'index':n,'vid':str(123456780000+n)} for n in (1,2)]),self.root/('metadata-'+str(closed)),encoder=encoder,profile_files=PROFILE_FILES)
            self.addCleanup(prefetch.close);prefetch.begin(Job(uuid.uuid4().hex,self.root/'job'), 'series',2)
            if closed:prefetch.close()
            with self.assertRaises(EncodingCancelled):prefetch.load_source('series',1 if not closed else 2)
            self.assertEqual(calls,[])

    def test_impossible_artifact_is_rejected_before_stage_or_copy(self):
        from desktop_playable_cache import CacheQuotaExceeded
        cache=self.cache();cache.quota_bytes=1
        before=set(cache.root.iterdir())
        with patch.object(cache,'_copy',side_effect=AssertionError('must not stage impossible artifact')) as copy:
            with self.assertRaises(ValueError):cache.store(self.source,self.output)
            copy.assert_not_called()
        self.assertEqual(set(cache.root.iterdir()),before)

    def test_complete_cache_rejects_delta_update_tag(self):
        path=self.output/'index.m3u8';s=path.read_text(encoding='utf8');path.write_text(s.replace('#EXTM3U\n','#EXTM3U\n#EXT-X-SKIP:SKIPPED-SEGMENTS=1\n',1),encoding='utf8')
        with self.assertRaises(ValueError):self.cache().store(self.source,self.output)

    def test_cache_hit_callbacks_recheck_cancellation(self):
        cache=self.cache();cache.store(self.source,self.output)
        for during_window in (False,True):
            with self.subTest(during_window=during_window):
                cancel=threading.Event();ready=[];restored=cache.restore;target=self.root/('callbacks-'+str(during_window))
                def restore(*a,**kw):
                    result=restored(*a,**kw)
                    if not during_window:cancel.set()
                    return result
                def window(*_):cancel.set()
                with patch.object(cache,'restore',restore):
                    with self.assertRaises(EncodingCancelled):cache.encode(self.source,target,lambda:ready.append(True),cancelled=cancel.is_set,start_seconds=1,on_window=window)
                self.assertEqual(ready,[])

    def test_download_preflight_skips_changed_generation_and_shutdown(self):
        from types import SimpleNamespace
        for shutdown in (False,True):
            calls=[];reported=[False];condition=threading.Condition()
            value=SimpleNamespace(condition=condition,closed=False,generation=1,download_pending=[(1,2,'old')],download_active=None,sources={},download_completed=[],failed=[])
            def report():
                if not reported[0]:
                    reported[0]=True
                    with condition:
                        if shutdown:value.closed=True
                        else:value.generation=2;value.download_pending=[(2,3,'new')]
                        condition.notify_all()
            def load(vid):
                calls.append(vid)
                with condition:value.closed=True;condition.notify_all()
                return 'source'
            value._report=report;value.download_loader=load
            worker=threading.Thread(target=EpisodePrefetcher._download,args=(value,),daemon=True);worker.start();worker.join(1)
            self.assertFalse(worker.is_alive());self.assertEqual(calls,[] if shutdown else ['new'])

    def test_profile_fingerprint_includes_names_lengths_and_empty_modules(self):
        one=self.root/'policy-one.py';two=self.root/'policy-two.py';one.write_bytes(b'ab');two.write_bytes(b'c')
        def profile(files):return PlayableEpisodeCache(self.root/'profile',encoder=encoder,profile_files=files).profile
        before=profile([one,two]);one.write_bytes(b'a');two.write_bytes(b'bc');self.assertNotEqual(before,profile([one,two]))
        empty=self.root/'optional.py';empty.write_bytes(b'');self.assertNotEqual(profile([one]),profile([one,empty]))
        other=self.root/'renamed.py';other.write_bytes(one.read_bytes());self.assertNotEqual(profile([one]),profile([other]))

    def test_complete_cache_rejects_parameterized_flag_tags(self):
        path=self.output/'index.m3u8';original=path.read_text(encoding='utf8')
        for tag in ('#EXT-X-GAP:YES','#EXT-X-I-FRAMES-ONLY:YES'):
            path.write_text(original.replace('#EXTM3U\n','#EXTM3U\n'+tag+'\n',1),encoding='utf8')
            with self.assertRaises(ValueError):self.cache().store(self.source,self.output)

    def test_prefetch_quota_keeps_current_and_nearer_episodes(self):
        for capacity in (1,2):
            with self.subTest(capacity=capacity):
                sources={str(10000000+n):self.root/('source-'+str(capacity)+'-'+str(n)) for n in range(1,5)}
                for vid,path in sources.items():path.write_bytes(vid.encode())
                episodes=[{'index':n,'vid':str(10000000+n)} for n in range(1,5)]
                value=EpisodePrefetcher(sources.get,lambda _:({},episodes),self.root/('quota-'+str(capacity)),encoder=encoder,profile_files=PROFILE_FILES)
                self.addCleanup(value.close);job=Job(uuid.uuid4().hex,self.root/('session-'+str(capacity)));value.begin(job,'series',1)
                source=value.load_source('series',1);value.before_work(job);value.encode(source,job.directory)
                entry=value.cache.root/value.cache._identity(source)[0]
                value.cache.quota_bytes=sum(p.stat().st_size for p in entry.iterdir())*capacity+65536
                value.finish(job,'series',1,source);self.assertTrue(value.wait_idle(3))
                self.assertTrue(value.cache.contains(source),'current episode remains resident')
                self.assertEqual(value.snapshot()['completedEpisodes'],list(range(2,capacity+1)))
                for n in range(2,capacity+1):self.assertTrue(value.cache.contains(sources[str(10000000+n)]))

    def test_complete_cache_rejects_preferred_start_tag(self):
        playlist=self.output/'index.m3u8';original=playlist.read_text(encoding='utf8')
        for offset in ('1','-1'):
            playlist.write_text(original.replace('#EXTM3U\n','#EXTM3U\n#EXT-X-START:TIME-OFFSET='+offset+'\n',1),encoding='utf8')
            with self.assertRaises(ValueError):self.cache().store(self.source,self.output)

    def test_partial_restore_cleanup_failure_does_not_call_encoder(self):
        cache=self.cache();cache.store(self.source,self.output);target=self.root/'partial';unlink=Path.unlink
        def copy(source,destination,cancelled):destination.write_bytes(b'partial');raise OSError('original copy failure')
        def remove(path,*args,**kwargs):
            if path.parent==target:raise OSError('sharing violation')
            return unlink(path,*args,**kwargs)
        with patch.object(cache,'_copy',copy),patch.object(Path,'unlink',remove),patch.object(cache,'encoder') as encode:
            with self.assertRaisesRegex(OSError,'original copy failure'):cache.encode(self.source,target)
            encode.assert_not_called()

    def test_complete_cache_rejects_master_playlist_tags(self):
        playlist=self.output/'index.m3u8';original=playlist.read_text(encoding='utf8')
        for tag in ('#EXT-X-STREAM-INF:BANDWIDTH=1000','#EXT-X-I-FRAME-STREAM-INF:BANDWIDTH=1000,URI="x"','#EXT-X-MEDIA:TYPE=AUDIO','#EXT-X-SESSION-DATA:DATA-ID="x",VALUE="y"'):
            with self.subTest(tag=tag):
                playlist.write_text(original.replace('#EXTM3U\n','#EXTM3U\n'+tag+'\n',1),encoding='utf8')
                with self.assertRaises(ValueError):self.cache().store(self.source,self.output)

    def test_restore_rollback_revokes_marker_first_and_preserves_cancellation(self):
        cache=self.cache();cache.store(self.source,self.output);destination=self.root/'restored';cancel=threading.Event();copy=cache._copy;unlink=Path.unlink;removed=[]
        def copy_then_cancel(source,target,check):
            copy(source,target,check)
            if target.name=='complete.marker':cancel.set()
        def remove(path,*args,**kwargs):
            if path.parent==destination:
                removed.append(path.name)
                if path.name=='init.mp4':raise OSError('owned cleanup sharing violation')
            return unlink(path,*args,**kwargs)
        with patch.object(cache,'_copy',copy_then_cancel),patch.object(Path,'unlink',remove):
            with self.assertRaises(EncodingCancelled):cache.restore(self.source,destination,cancel.is_set)
        self.assertEqual(removed[0],'complete.marker');self.assertFalse((destination/'complete.marker').exists())
        self.assertIn('index.m3u8',removed);self.assertIn('seg000000.m4s',removed)

    def test_fresh_stage_rmdir_failure_restores_owned_marker(self):
        from desktop_playable_cache import OWNER
        cache=self.cache();stage=cache.root/('stage-'+uuid.uuid4().hex);stage.mkdir();(stage/'owner.marker').write_text(OWNER,encoding='ascii');(stage/'seg000000.m4s').write_bytes(b'x')
        rmdir=Path.rmdir
        def blocked(path):
            if path==stage:raise OSError('transient sharing failure')
            return rmdir(path)
        with patch.object(Path,'rmdir',blocked):
            with self.assertRaises(OSError):cache._remove_fresh_stage(stage)
        self.assertTrue((stage/'owner.marker').is_file());cache._owned_children(stage);cache._remove_owned(stage)

    def _native_download_fixture(self, download):
        episodes=[{'index':n,'vid':str(10000000+n)} for n in range(1,5)]
        value=EpisodePrefetcher(lambda _:self.source,lambda _:({},episodes),self.root/'download-cache',encoder=encoder,profile_files=PROFILE_FILES,download_loader=download)
        self.addCleanup(value.close)
        job=Job(uuid.uuid4().hex,self.root/'native-session');job.video_mode='native'
        value.begin(job,'series',1)
        return value,job

    def test_native_download_failure_is_reported_without_hls_worker(self):
        def download(vid):
            if vid=='10000002':raise OSError('private transport detail')
            return self.source
        value,job=self._native_download_fixture(download)
        source=value.load_source('series',1);value.finish(job,'series',1,source)
        self.assertTrue(value.wait_idle(2));state=value.snapshot()
        self.assertEqual(state['failedEpisodes'],[2]);self.assertEqual(state['downloadCompletedEpisodes'],[3,4])
        self.assertEqual(state['failureCode'],'preparation-failed');self.assertIsNone(value.worker)
        self.assertNotIn('private',json.dumps(state))

    def test_native_download_thread_failure_reports_all_pending_episodes(self):
        value,job=self._native_download_fixture(lambda _:self.source)
        with patch('desktop_prefetch.threading.Thread.start',side_effect=RuntimeError('thread limit')):
            source=value.load_source('series',1)
        value.finish(job,'series',1,source);self.assertTrue(value.wait_idle(.1))
        self.assertEqual(value.snapshot()['failedEpisodes'],[2,3,4]);self.assertIsNone(value.worker)

    def test_stale_download_failure_cannot_pollute_new_generation(self):
        entered,release=threading.Event(),threading.Event();self.addCleanup(release.set)
        def download(_):
            entered.set();release.wait(2);raise OSError('old generation failed')
        value,job=self._native_download_fixture(download)
        source=value.load_source('series',1);self.assertTrue(entered.wait(1))
        newer=Job(uuid.uuid4().hex,self.root/'new-session');value.begin(newer,'series',4)
        value.finish(job,'series',1,source);value.finish(newer,'series',4,None)
        release.set();self.assertTrue(value.wait_idle(2));self.assertEqual(value.snapshot()['failedEpisodes'],[])

    def test_complete_cache_rejects_discontinuous_and_invalid_sequence_tags(self):
        playlist=self.output/'index.m3u8';original=playlist.read_text(encoding='utf8');cache=self.cache()
        for tag in ('#EXT-X-DISCONTINUITY','#EXT-X-DISCONTINUITY-SEQUENCE:0',
                    '#EXT-X-DISCONTINUITY-SEQUENCE:bad','#EXT-X-MEDIA-SEQUENCE:bad',
                    '#EXT-X-MEDIA-SEQUENCE:0\n#EXT-X-MEDIA-SEQUENCE:1'):
            for body in (original.replace('#EXTM3U\n','#EXTM3U\n'+tag+'\n',1),original+tag+'\n'):
                with self.subTest(tag=tag):
                    playlist.write_text(body,encoding='utf8')
                    with self.assertRaises(ValueError):cache.store(self.source,self.output)
        playlist.write_text(original+'#EXT-X-MEDIA-SEQUENCE:0\n',encoding='utf8')
        with self.assertRaises(ValueError):cache.store(self.source,self.output)
        playlist.write_text(original.replace('#EXTM3U\n','#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:0\n',1),encoding='utf8');self.assertTrue(cache.store(self.source,self.output))

    def test_dangling_exact_target_is_rejected_before_quota_eviction(self):
        cache=self.cache();key,_=cache._identity(self.source);target=cache.root/key
        try: target.symlink_to(cache.root/'absent',target_is_directory=True)
        except OSError as error:self.skipTest(str(error))
        with patch.object(cache,'_reserve',side_effect=AssertionError('must reject before quota')):
            with self.assertRaises((ValueError,OSError)):cache.store(self.source,self.output)

    def test_replacement_finishes_if_cancelled_during_destructive_remove(self):
        cache=self.cache();target=cache.store(self.source,self.output);cancel=threading.Event()
        remove=cache._remove_owned
        def interrupted(directory,cancelled=lambda:False):
            if directory==target:cancel.set()
            return remove(directory,cancelled)
        with patch.object(cache,'_remove_owned',interrupted):
            self.assertEqual(cache.store(self.source,self.output,cancel.is_set),target)
        self.assertTrue(cache.contains(self.source));self.assertEqual(list(cache.root.glob('stage-*')),[])

    def test_cold_encode_hashes_stable_source_once(self):
        cache=self.cache();digest=cache._digest;reads=[]
        def counted(path,cancelled=lambda:False):
            if path==self.source:reads.append(path)
            return digest(path,cancelled)
        with patch.object(cache,'_digest',counted):
            self.assertTrue(cache.encode(self.source,self.root/'cold-encode'))
        self.assertEqual(len(reads),1)

    def test_fresh_stage_removal_failure_keeps_owner_marker(self):
        cache=self.cache();stage=cache.root/('stage-'+uuid.uuid4().hex);stage.mkdir()
        (stage/'owner.marker').write_text('desktop-playable-cache-v1',encoding='ascii')
        (stage/'seg000000.m4s').write_bytes(b'media');unlink=Path.unlink
        def denied(path,*args,**kwargs):
            if path.name=='seg000000.m4s':raise PermissionError('locked')
            return unlink(path,*args,**kwargs)
        with patch.object(Path,'unlink',denied):
            with self.assertRaises(PermissionError):cache._remove_fresh_stage(stage)
        self.assertTrue((stage/'owner.marker').exists());cache._remove_owned(stage)

    def test_complete_cache_playlist_type_is_unique_and_known(self):
        path=self.output/'index.m3u8';original=path.read_text(encoding='utf8');cache=self.cache()
        for tag in ('#EXT-X-PLAYLIST-TYPE:OTHER','#EXT-X-PLAYLIST-TYPE',
                    '#EXT-X-PLAYLIST-TYPE:VOD\n#EXT-X-PLAYLIST-TYPE:VOD'):
            path.write_text(original+tag+'\n',encoding='utf8')
            with self.assertRaises(ValueError):cache.store(self.source,self.output)
        for tag in ('EVENT','VOD'):
            path.write_text(original+'#EXT-X-PLAYLIST-TYPE:'+tag+'\n',encoding='utf8')
            self.assertTrue(cache.store(self.source,self.output))

    def test_resumed_full_cache_restores_without_encoder(self):
        cache=self.cache();cache.store(self.source,self.output);windows=[];ready=[]
        cache.encoder=lambda *a,**kw:self.fail('cache hit must not encode a seek window')
        self.assertTrue(cache.encode(self.source,self.root/'resumed',lambda:ready.append(True),start_seconds=1,on_window=lambda *v:windows.append(v)))
        self.assertEqual(windows,[(0,None)]);self.assertEqual(ready,[True])
        self.assertEqual((self.root/'resumed/index.m3u8').read_bytes(),(self.output/'index.m3u8').read_bytes())

    def test_finish_reuses_foreground_cache_validation(self):
        value=EpisodePrefetcher(lambda _:self.source,lambda _:({},[{'index':1,'vid':'10000001'}]),
            self.root/'reuse-cache',encoder=encoder,ahead=0,profile_files=PROFILE_FILES)
        self.addCleanup(value.close);job=Job('owned',self.root/'foreground');value.begin(job,'series',1)
        source=value.load_source('series',1);value.before_work(job);value.encode(source,job.directory)
        with patch.object(value.cache,'contains',side_effect=AssertionError('duplicate full source/artifact hash')) as contains:
            value.finish(job,'series',1,source);contains.assert_not_called()
        self.assertTrue(value.current_complete);self.assertIsNone(value.busy);self.assertEqual(value.foreground,{})

    def test_closed_report_restarts_a_terminated_writer(self):
        value=EpisodePrefetcher(lambda _:None,lambda _:({},[]),self.root/'report-cache',encoder=encoder,profile_files=PROFILE_FILES)
        value.status_path=self.root/'writer-status.json';dead=threading.Thread(target=lambda:None);dead.start();dead.join();value.reporter=dead
        value.close();until=time.monotonic()+2
        while time.monotonic()<until:
            try:
                if json.loads(value.status_path.read_text())['state']=='closed':break
            except (OSError,ValueError):pass
            time.sleep(.01)
        self.assertEqual(json.loads(value.status_path.read_text())['state'],'closed')

    def test_optional_source_status_never_blocks_foreground_load(self):
        for reporting in (False,True):
            with self.subTest(reporting=reporting):
                gate,loaded=threading.Event(),threading.Event();errors=[]
                def status(_):gate.wait(2);return {'complete':True}
                value=EpisodePrefetcher(lambda _:self.source,lambda _:({},[{'index':1,'vid':'10000001'}]),
                    self.root/uuid.uuid4().hex,encoder=encoder,source_status=status,profile_files=PROFILE_FILES,
                    status_path=self.root/'status.json' if reporting else None)
                value.begin(Job(uuid.uuid4().hex,self.root/'session'),'series',1)
                def load():
                    try:self.assertEqual(value.load_source('series',1),self.source);loaded.set()
                    except BaseException as exc:errors.append(exc)
                worker=threading.Thread(target=load);worker.start()
                try:self.assertTrue(loaded.wait(.5),'foreground cannot await the optional callback')
                finally:gate.set();worker.join(2);value.close()
                self.assertEqual(errors,[])

    def test_background_stage_marker_failure_reclaims_known_encoder_outputs(self):
        for partial in (False,True):
            with self.subTest(partial=partial):
                value=EpisodePrefetcher(lambda _:None,lambda _:({},[]),self.root/uuid.uuid4().hex,
                    encoder=encoder,profile_files=PROFILE_FILES)
                value.current={'episode':1};value.pending=[(0,2,'10000002','h264')];value.sources['10000002']=self.source
                original=Path.write_text
                def write(path,data,*args,**kwargs):
                    if path.name=='owner.marker':
                        if partial:original(path,'partial',encoding='ascii')
                        raise OSError('fixture disk full')
                    return original(path,data,*args,**kwargs)
                worker=threading.Thread(target=value._run);value.worker=worker
                with patch.object(Path,'write_text',write):
                    worker.start()
                    try:
                        self.assertTrue(value.wait_idle(2));self.assertEqual(value.failed,[2])
                        self.assertEqual(list(value.cache.root.glob('stage-*')),[])
                    finally:value.close();worker.join(2)

    def test_fresh_stage_cleanup_preserves_unknown_or_reparse_content(self):
        cache=self.cache();stage=cache.root/('stage-'+'c'*32);stage.mkdir()
        (stage/'seg000000.m4s').write_bytes(b'owned');(stage/'unknown').write_bytes(b'preserve')
        with self.assertRaises(ValueError):cache._remove_fresh_stage(stage)
        self.assertEqual((stage/'unknown').read_bytes(),b'preserve')
        self.assertTrue((stage/'seg000000.m4s').exists(),'validate every file before any deletion')
    def test_stale_metadata_never_starts_media_loading(self):
        for closed in (False,True):
            with self.subTest(closed=closed):
                loaded=[];value=None
                def metadata(_):
                    if closed:value.close()
                    else:value.begin(Job(uuid.uuid4().hex,self.root/uuid.uuid4().hex),'12345678',2)
                    return {},[{'index':1,'vid':'10000001'}]
                value=EpisodePrefetcher(loaded.append,metadata,self.root/'cache',encoder=encoder,profile_files=PROFILE_FILES)
                value.begin(Job(uuid.uuid4().hex,self.root/uuid.uuid4().hex),'12345678',1)
                try:
                    with self.assertRaises(EncodingCancelled):value.load_source('12345678',1)
                    self.assertEqual(loaded,[])
                finally:value.close()

    def test_new_stage_marker_failure_leaves_no_partial_directory(self):
        cache=self.cache();original=Path.write_text
        def no_marker(path,data,*args,**kwargs):
            if path.name=='owner.marker':
                original(path,'partial',encoding='ascii')
                raise OSError('fixture disk full')
            return original(path,data,*args,**kwargs)
        with patch.object(Path,'write_text',no_marker):
            with self.assertRaises(OSError):cache.store(self.source,self.output)
        self.assertEqual(list(cache.root.glob('stage-*')),[])

    def test_numbered_fragment_gap_cannot_enter_complete_cache(self):
        cache=self.cache();playlist=self.output/'index.m3u8'
        (self.output/'seg000002.m4s').write_bytes(b'later')
        playlist.write_text(playlist.read_text(encoding='utf8').replace('#EXT-X-ENDLIST',
            '#EXTINF:2,\nseg000002.m4s\n#EXT-X-ENDLIST'),encoding='utf8')
        with self.assertRaises(ValueError):cache.store(self.source,self.output)
    def test_optional_diagnostic_cannot_hold_background_encoder_slot(self):
        entered,release,encoded=threading.Event(),threading.Event(),threading.Event()
        def status(_):
            entered.set();release.wait(2);return {'complete':False}
        def encode(*args,**kwargs):
            encoded.set();release.wait(2);raise EncodingCancelled()
        value=EpisodePrefetcher(lambda _:None,lambda _:({},[]),self.root/'cache',
            encoder=encode,source_status=status,profile_files=PROFILE_FILES)
        value.status_path=self.root/'status.json';value.current_source=self.source
        value.current={'episode':1};value.pending=[(0,1,'10000001','h264')];value.sources['10000001']=self.source
        worker=threading.Thread(target=value._run);value.worker=worker;worker.start()
        try:
            self.assertTrue(entered.wait(1))
            self.assertTrue(encoded.wait(.5),'optional diagnostic must run outside the encoder worker')
        finally:release.set();value.close();worker.join(2)

    def test_same_generation_old_report_cannot_overwrite_new_completion(self):
        entered,release=threading.Event(),threading.Event();count=[0]
        value=EpisodePrefetcher(lambda _:None,lambda _:({},[]),self.root/'cache',encoder=encoder,profile_files=PROFILE_FILES)
        value.status_path=self.root/'status.json'
        def snapshot():
            count[0]+=1
            if count[0]==1:
                entered.set();release.wait(2);return {'completedEpisodes':[]}
            return {'completedEpisodes':[2]}
        value.snapshot=snapshot
        first=threading.Thread(target=value._report);first.start()
        try:
            self.assertTrue(entered.wait(1));value._report();release.set();first.join(2)
            deadline=time.monotonic()+2
            while time.monotonic()<deadline:
                try:
                    if json.loads(value.status_path.read_text())=={'completedEpisodes':[2]}:break
                except (OSError,ValueError):pass
                time.sleep(.01)
            self.assertEqual(json.loads(value.status_path.read_text()),{'completedEpisodes':[2]})
        finally:release.set();value.close();first.join(2)

    def test_file_shaped_stage_counts_as_non_evictable_quota(self):
        cache=self.cache()
        stage=cache.root/('stage-'+'a'*32)
        stage.write_bytes(b'x'*128)
        cache.quota_bytes=100
        with self.assertRaises(OSError):cache._reserve(1)
        self.assertEqual(stage.read_bytes(),b'x'*128)

    def test_blocked_source_snapshot_does_not_hold_scheduler_condition(self):
        entered,release,changed=threading.Event(),threading.Event(),threading.Event()
        def status(_):
            entered.set();release.wait(2);return {'complete':False}
        prefetch=EpisodePrefetcher(lambda _:None,lambda _:({},[]),self.root/'cache',
            encoder=encoder,source_status=status,profile_files=PROFILE_FILES,status_path=self.root/"status.json")
        self.addCleanup(prefetch.close)
        prefetch.current_source=object()
        reader=threading.Thread(target=prefetch._report);reader.start()
        self.assertTrue(entered.wait(1))
        writer=threading.Thread(target=lambda:(prefetch.begin(Job('new',self.root/'job'),'1234567890123456',2),changed.set()))
        writer.start()
        try:self.assertTrue(changed.wait(.5),'optional source status must not block episode switching')
        finally:release.set();reader.join(2);writer.join(2)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source.mp4';self.source.write_bytes(b'fixture')
        self.output=self.root/'output';complete_output(self.output)
    def cache(self,root=None):
        return PlayableEpisodeCache(root or self.root/'cache',encoder=encoder,profile_files=PROFILE_FILES)
    def test_non_json_source_identity_cannot_fail_successful_encode(self):
        class Source:
            def cache_identity(self):return {'contentHash':b'bytes'}
        cache=self.cache();target=self.root/'encoded'
        cache.encode(Source(),target)
        self.assertTrue((target/'complete.marker').exists())

    def test_json_identity_roundtrip_remains_a_cache_hit(self):
        class Source:
            def cache_identity(self):return {'tracks':(1,2),'rendition':{7:'HD'}}
        cache=self.cache();source=Source();cache.store(source,self.output)
        self.assertTrue(cache.contains(source))
        self.assertTrue(cache.restore(source,self.root/'restored-json'))

    def test_hit_ready_callback_error_does_not_encode_again(self):
        cache=self.cache();cache.store(self.source,self.output)
        def ready():raise RuntimeError('ready failed')
        with patch.object(cache,'encoder') as encode:
            with self.assertRaisesRegex(RuntimeError,'ready failed'):
                cache.encode(self.source,self.root/'restored-callback',ready)
            encode.assert_not_called()

    def test_cancel_during_quota_scan_preserves_existing_entries(self):
        cache=self.cache();target=cache.store(self.source,self.output)
        cache.quota_bytes=sum(p.stat().st_size for p in target.iterdir())+65536
        before={p.name:p.read_bytes() for p in target.iterdir()}
        self.source.write_bytes(b'changed');stopped=threading.Event();original=Path.iterdir
        def scan(path):
            children=list(original(path))
            if path==cache.root:stopped.set()
            return iter(children)
        with patch.object(Path,'iterdir',scan):
            with self.assertRaises(EncodingCancelled):
                cache.store(self.source,self.output,cancelled=stopped.is_set)
        self.assertEqual(before,{p.name:p.read_bytes() for p in target.iterdir()})

    def test_cancel_after_reservation_does_not_replace_target(self):
        cache=self.cache();target=cache.store(self.source,self.output)
        before={p.name:p.read_bytes() for p in target.iterdir()};stopped=threading.Event()
        with patch.object(cache,'_reserve',side_effect=lambda *a,**k:stopped.set()):
            with self.assertRaises(EncodingCancelled):
                cache.store(self.source,self.output,cancelled=stopped.is_set)
        self.assertEqual(before,{p.name:p.read_bytes() for p in target.iterdir()})

    def test_iframe_only_artifact_is_not_stored_as_normal_playback(self):
        cache=self.cache();playlist=self.output/'index.m3u8'
        playlist.write_text(playlist.read_text(encoding='utf-8').replace('#EXTM3U\n','#EXTM3U\n#EXT-X-I-FRAMES-ONLY\n'),encoding='utf-8')
        with self.assertRaises(ValueError):cache.store(self.source,self.output)

    def test_completion_callback_failure_always_releases_encoder_ownership(self):
        value=EpisodePrefetcher(lambda _:self.source,lambda _:({},[{'index':1,'vid':'10000001'}]),self.root/'cache',encoder=encoder,profile_files=PROFILE_FILES)
        self.addCleanup(value.close)
        job=Job(uuid.uuid4().hex,self.root/'session');value.begin(job,'series',1)
        source=value.load_source('series',1);value.before_work(job)
        value.cache.available=False
        with patch.object(value.cache,'contains',side_effect=RuntimeError('transient identity failure')):
            value.finish(job,'series',1,source)
        self.assertIsNone(value.busy);self.assertNotIn(job.id,value.foreground)
        next_job=Job(uuid.uuid4().hex,self.root/'next');value.begin(next_job,'series',2)
        value.before_work(next_job);self.assertEqual(value.busy,next_job.id)

    def test_host_profile_and_video_mode_are_not_overwritten_by_cache_metadata(self):
        class Source:
            def __init__(self,profile):self.profile=profile
            def cache_identity(self):return {'vid':'10000001','profile':self.profile,'videoMode':'host-owned'}
        cache=self.cache();first,second=Source('720p'),Source('1080p')
        a=cache.store(first,self.output)
        self.assertFalse(cache.contains(second));self.assertFalse(cache.restore(second,self.root/'wrong-rendition'))
        b=cache.store(second,self.output)
        self.assertNotEqual(a,b);self.assertTrue(cache.contains(first));self.assertTrue(cache.contains(second))

    def test_protected_replacement_is_rejected_before_reservation(self):
        cache=self.cache();target=cache.store(self.source,self.output)
        other=self.root/'other';other.write_bytes(b'other');unrelated=cache.store(other,self.output)
        (target/'owner.marker').write_bytes(b'unknown')
        before={p.name:p.read_bytes() for p in unrelated.iterdir()}
        with patch.object(cache,'_reserve',wraps=cache._reserve) as reserve:
            with self.assertRaises(ValueError):cache.store(self.source,self.output)
            reserve.assert_not_called()
        self.assertEqual(before,{p.name:p.read_bytes() for p in unrelated.iterdir()})

    def test_replacement_credits_old_target_without_evicting_unrelated_lru(self):
        cache=self.cache();(self.output/'seg000000.m4s').write_bytes(b'x'*100000)
        target=cache.store(self.source,self.output)
        other=self.root/'other';other.write_bytes(b'other')
        unrelated=cache.store(other,self.output)
        os.utime(unrelated/'cache.json',ns=(1,1));os.utime(target/'cache.json',ns=(2,2))
        cache.quota_bytes=sum(p.stat().st_size for d in cache.root.iterdir() for p in d.iterdir())+65536+4096
        cache.store(self.source,self.output)
        self.assertTrue(cache.contains(other),'replacement must preserve unrelated older cache')
        self.assertTrue(cache.contains(self.source))

    def test_disabled_cache_keeps_foreground_and_original_downloads_without_recoding(self):
        disabled=self.root/'not-a-directory';disabled.write_bytes(b'file')
        downloads=[];encodes=[]
        def encode(*args,**kwargs):encodes.append(True);encoder(*args,**kwargs)
        episodes=[{'index':n,'vid':str(10000000+n)} for n in range(1,5)]
        value=EpisodePrefetcher(lambda _:self.source,lambda _:({},episodes),disabled,encoder=encode,
            download_loader=lambda vid:(downloads.append(vid),self.source)[1],profile_files=PROFILE_FILES)
        self.addCleanup(value.close);self.assertFalse(value.cache.available)
        job=Job(uuid.uuid4().hex,self.root/'session');value.begin(job,'series',1)
        source=value.load_source('series',1);value.before_work(job);value.encode(source,job.directory)
        value.finish(job,'series',1,source)
        self.assertTrue(value.wait_idle(2));self.assertEqual(len(encodes),1)
        self.assertEqual(len(downloads),3);self.assertFalse(value.failed);self.assertFalse(value.pending)

    def test_optional_status_failure_cannot_abort_loaded_source(self):
        callbacks=(lambda _:(_ for _ in ()).throw(RuntimeError('temporary')),
                   lambda _: {},lambda _:None)
        for callback in callbacks:
            value=EpisodePrefetcher(lambda _:self.source,lambda _:({},[{'index':1,'vid':'10000001'}]),
                self.root/uuid.uuid4().hex,encoder=encoder,source_status=callback,profile_files=PROFILE_FILES)
            job=Job(uuid.uuid4().hex,self.root/'session');value.begin(job,'series',1)
            try:
                self.assertIs(value.load_source('series',1),self.source)
                self.assertFalse(value.snapshot()['currentSourceComplete'])
            finally:value.close()

    def test_optional_status_callback_and_serialization_errors_are_contained(self):
        value=EpisodePrefetcher(lambda _:self.source,lambda _:({},[]),self.root/'cache',
            encoder=encoder,profile_files=PROFILE_FILES,status_path=self.root/'status.json')
        value.current_source=object()
        for callback in (lambda _:(_ for _ in ()).throw(RuntimeError('teardown')),
                         lambda _:dict(complete=object())):
            value.source_status=callback
            value._report();value.close()

    def test_complete_cache_rejects_encryption_and_gap_tags(self):
        cache=self.cache();playlist=self.output/'index.m3u8';original=playlist.read_text(encoding='utf-8')
        for tag in ('#EXT-X-GAP','#EXT-X-BYTERANGE:10@1000000','#EXT-X-KEY:METHOD=AES-128,URI="missing"','#EXT-X-SESSION-KEY:METHOD=AES-128,URI="missing"'):
            playlist.write_text(original.replace('#EXTINF:',tag+'\n#EXTINF:',1),encoding='utf-8')
            with self.assertRaises(ValueError):cache.store(self.source,self.output)
    def test_nested_unknown_stage_counts_towards_quota_without_deletion(self):
        cache=self.cache();stage=cache.root/('stage-'+'a'*32)
        (stage/'unknown').mkdir(parents=True)
        payload=stage/'unknown'/'data';payload.write_bytes(b'x'*1000)
        cache.quota_bytes=1000
        with self.assertRaises(OSError):cache._reserve(1)
        self.assertEqual(payload.read_bytes(),b'x'*1000)

    def test_cancellation_during_commit_hash_preserves_lru(self):
        cache=self.cache();target=cache.store(self.source,self.output)
        self.source.write_bytes(b'changed')
        cache.quota_bytes=sum(p.stat().st_size for p in target.iterdir())+65536
        stopped=threading.Event();original=cache._digest
        def digest(path,cancelled=lambda:False):
            if path.name=='seg000000.m4s':stopped.set()
            return original(path,cancelled)
        with patch.object(cache,'_digest',side_effect=digest):
            with self.assertRaises(EncodingCancelled):cache.store(self.source,self.output,stopped.is_set)
        self.assertTrue((target/'complete.marker').exists())

    def test_new_generation_prefetch_runs_while_stale_loader_is_blocked(self):
        encoded=threading.Event()
        episodes=[{'index':n,'vid':str(10000000+n)} for n in (1,2)]
        def encode(*args,**kwargs):encoder(*args,**kwargs);encoded.set()
        value=EpisodePrefetcher(lambda _:self.source,lambda _:({},episodes),self.root/'cache',
            encoder=encode,profile_files=PROFILE_FILES,ahead=0)
        self.addCleanup(value.close)
        old=Job(uuid.uuid4().hex,self.root/'old');value.begin(old,'series',1)
        new=Job(uuid.uuid4().hex,self.root/'new');value.begin(new,'series',2)
        source=value.load_source('series',2);value.before_work(new)
        value.finish(new,'series',2,source)
        self.assertTrue(encoded.wait(1),'stale foreground must not block current background')
        old.cancelled.set();value.finish(old,'series',1,None)

    def test_background_cancel_does_not_evict_before_encode(self):
        entered=threading.Event();release=threading.Event()
        def encode(*args,**kwargs):
            entered.set();release.wait(2);raise EncodingCancelled()
        value=EpisodePrefetcher(lambda _:self.source,lambda _:({},[{'index':1,'vid':'10000001'}]),
            self.root/'cache',encoder=encode,profile_files=PROFILE_FILES,ahead=0)
        self.addCleanup(value.close)
        target=value.cache.store(self.source,self.output)
        value.cache.quota_bytes=sum(p.stat().st_size for p in target.iterdir())+65536
        self.source.write_bytes(b'new source')
        job=Job(uuid.uuid4().hex,self.root/'job');value.begin(job,'series',1)
        source=value.load_source('series',1);value.finish(job,'series',1,source)
        try:
            self.assertTrue(entered.wait(1));self.assertTrue(target.exists())
        finally:release.set()
    def test_single_endlist_is_valid_anywhere_but_trailing_extinf_is_not_complete(self):
        cache=self.cache();playlist=self.output/'index.m3u8'
        body=playlist.read_text(encoding='utf-8').replace('#EXT-X-ENDLIST\n','')
        for anchor in ('#EXT-X-MAP:', '#EXTINF:', 'seg000000.m4s'):
            with self.subTest(anchor=anchor):
                playlist.write_text(body.replace(anchor,'#EXT-X-ENDLIST\n'+anchor,1),encoding='utf-8')
                cache.store(self.source,self.output);self.assertTrue(cache.contains(self.source))
        playlist.write_text(body+'#EXT-X-ENDLIST\n#EXTINF:2,\n',encoding='utf-8')
        with self.assertRaises(ValueError):cache.store(self.source,self.output)

    def test_inaccessible_optional_cache_does_not_break_construction(self):
        blocked=self.root/'not-directory';blocked.write_bytes(b'file')
        cache=self.cache(blocked/'cache')
        self.assertFalse(cache.contains(self.source))
        with patch('desktop_playable_cache.plain',side_effect=PermissionError('denied')):
            disabled=self.cache(self.root/'denied')
        self.assertFalse(disabled.contains(self.source))
    def test_bad_owner_bytes_are_unowned_not_a_scan_failure(self):
        cache=self.cache();unknown=cache.root/('f'*64);unknown.mkdir()
        (unknown/'owner.marker').write_bytes(b'\xff');(unknown/'data').write_bytes(b'unknown')
        cache.store(self.source,self.output)
        self.assertTrue(cache.contains(self.source));self.assertTrue((unknown/'data').exists())
    def test_cancelled_store_does_not_reserve_or_evict(self):
        cache=self.cache()
        with patch.object(cache,'_reserve',wraps=cache._reserve) as reserve:
            with self.assertRaises(EncodingCancelled):cache.store(self.source,self.output,cancelled=lambda:True)
            reserve.assert_not_called()
    def test_unavailable_store_does_not_read_source_or_media(self):
        cache=self.cache();cache.available=False
        with patch.object(cache,'_identity',side_effect=AssertionError('unneeded hash')):
            self.assertIsNone(cache.store(self.source,self.output))
    def test_impossible_reservation_preserves_existing_owned_cache(self):
        cache=self.cache();target=cache.store(self.source,self.output)
        before={p.name:p.read_bytes() for p in target.iterdir()}
        for needed in (cache.quota_bytes+1, cache.quota_bytes):
            with self.subTest(needed=needed):
                unknown=cache.root/('e'*64)
                unknown.mkdir(exist_ok=True);(unknown/'owner.marker').write_bytes(b'unknown')
                with self.assertRaises(OSError):cache._reserve(needed)
                self.assertEqual(before,{p.name:p.read_bytes() for p in target.iterdir()})
    def test_seek_window_forwards_explicit_copy_mode(self):
        cache=self.cache()
        with patch.object(cache,'encoder') as encode:
            cache.encode(self.source,self.root/'seek',start_seconds=1,video_mode='copy')
        self.assertEqual(encode.call_args.kwargs['video_mode'],'copy')
    def test_source_and_artifact_hashing_can_be_cancelled_mid_read(self):
        cache=self.cache()
        self.source.write_bytes(b'x'*(3*1024*1024))
        (self.output/'seg000000.m4s').write_bytes(b'x'*(3*1024*1024))
        stored=cache.store(self.source,self.output)
        class SlowRead:
            def __init__(self, stream, stopped):self.stream,self.stopped=stream,stopped
            def __enter__(self):return self
            def __exit__(self,*a):self.stream.close()
            def read(self,size):
                value=self.stream.read(size);self.stopped.set();return value
        original=Path.open
        for cancelled_path in (self.source,stored/'seg000000.m4s'):
            for operation in ('contains','restore'):
                stopped=threading.Event()
                def open_file(path,*a,**kw):
                    stream=original(path,*a,**kw)
                    return SlowRead(stream,stopped) if path==cancelled_path and a and a[0]=='rb' else stream
                with patch.object(Path,'open',open_file):
                    with self.assertRaises(EncodingCancelled):
                        if operation=='contains':cache.contains(self.source,cancelled=stopped.is_set)
                        else:cache.restore(self.source,self.root/'restored-cancelled',stopped.is_set)
                self.assertFalse((self.root/'restored-cancelled').exists())
    def test_background_validation_cancels_and_releases_scheduler_slot_on_switch(self):
        future=self.root/'future.mp4';future.write_bytes(b'future')
        episodes=[{'index':n,'vid':str(10000000+n)} for n in (1,2)]
        value=EpisodePrefetcher(lambda vid:self.source if vid=='10000001' else future,
            lambda _:({},episodes),self.root/'cache',encoder=encoder,profile_files=PROFILE_FILES)
        self.addCleanup(value.close)
        job=Job(uuid.uuid4().hex,self.root/'current');value.begin(job,'series',1)
        source=value.load_source('series',1);value.before_work(job)
        value.cache.encode(source,job.directory)
        entered,release=threading.Event(),threading.Event();original=value.cache._digest
        def digest(path,cancelled=lambda:False):
            if path==future:entered.set();release.wait(2)
            return original(path,cancelled)
        with patch.object(value.cache,'_digest',side_effect=digest):
            value.finish(job,'series',1,source);self.assertTrue(entered.wait(1))
            new=Job(uuid.uuid4().hex,self.root/'next');value.begin(new,'series',2);release.set()
            started=time.monotonic();value.before_work(new)
            self.assertLess(time.monotonic()-started,.5)
        new.failed=True;value.finish(new,'series',2,None)
    def test_lru_touch_failure_preserves_a_valid_hit(self):
        cache=self.cache();cache.store(self.source,self.output);target=self.root/'restored'
        with patch('desktop_playable_cache.os.utime',side_effect=PermissionError('read only')):
            self.assertTrue(cache.restore(self.source,target))
        self.assertTrue((target/'complete.marker').is_file())
    def test_finish_does_not_hold_scheduler_lock_during_cache_io(self):
        value=EpisodePrefetcher(lambda _:self.source,lambda _:({},[{'index':1,'vid':'10000001'}]),self.root/'cache',encoder=encoder,profile_files=PROFILE_FILES)
        self.addCleanup(value.close)
        job=Job(uuid.uuid4().hex,self.root/'session');value.begin(job,'series',1);source=value.load_source('series',1)
        entered,release,switched=threading.Event(),threading.Event(),threading.Event()
        def contains(*a,**kw):entered.set();release.wait(2);return False
        def switch():value.begin(Job(uuid.uuid4().hex,self.root/'next'),'series',2);switched.set()
        with patch.object(value.cache,'contains',side_effect=contains):
            finish=threading.Thread(target=lambda:value.finish(job,'series',1,source));finish.start()
            self.assertTrue(entered.wait(1));change=threading.Thread(target=switch);change.start()
            responsive=switched.wait(.4);release.set();finish.join(2);change.join(2)
        self.assertTrue(responsive,'begin must not wait for full-source/full-cache hashing')
        self.assertFalse(value.pending,'old completion must not publish into the new generation')

    def test_native_progressive_current_downloads_three_originals_without_encoding(self):
        source=object();downloads=[];encodes=[]
        episodes=[{'index':n,'vid':str(10000000+n)} for n in range(1,5)]
        def download(vid):downloads.append(int(vid)-10000000);return self.source
        value=EpisodePrefetcher(lambda _:source,lambda _:({},episodes),self.root/'cache',encoder=lambda *a,**k:encodes.append(a),profile_files=PROFILE_FILES,download_loader=download,source_status=lambda _:dict(kind='progressive',complete=False))
        self.addCleanup(value.close)
        job=Job(uuid.uuid4().hex,self.root/'session');job.video_mode='native'
        value.begin(job,'series',1);current=value.load_source('series',1);value.finish(job,'series',1,current)
        self.assertTrue(value.wait_idle(2));self.assertEqual(downloads,[2,3,4]);self.assertFalse(encodes)
        self.assertEqual(value.snapshot()['cacheKind'],'original-media');self.assertFalse(value.snapshot()['currentSourceComplete'])
    def test_blocked_stale_source_loading_does_not_reserve_encoder(self):
        entered,release=threading.Event(),threading.Event()
        episodes=[{'index':n,'vid':str(10000000+n)} for n in (1,2)]
        def load(vid):
            if vid=='10000001':entered.set();release.wait(2)
            return self.source
        value=EpisodePrefetcher(load,lambda _:({},episodes),self.root/'cache',encoder=encoder,profile_files=PROFILE_FILES,ahead=0)
        self.addCleanup(value.close)
        old=Job(uuid.uuid4().hex,self.root/'old');value.begin(old,'series',1)
        loading=threading.Thread(target=lambda:value.load_source('series',1));loading.start();self.assertTrue(entered.wait(1))
        new=Job(uuid.uuid4().hex,self.root/'new');value.begin(new,'series',2)
        try:
            value.before_work(new);self.assertEqual(value.busy,new.id)
        finally:release.set();loading.join(2)
        old.cancelled.set();value.finish(old,'series',1,None);new.failed=True;value.finish(new,'series',2,None)

    def test_unknown_stage_content_is_not_adopted_or_deleted(self):
        from desktop_playable_cache import OWNER
        for nested in (True, False):
            cache=self.cache(self.root/uuid.uuid4().hex)
            stage=cache.root/('stage-'+uuid.uuid4().hex);complete_output(stage)
            (stage/'owner.marker').write_text(OWNER,encoding='ascii')
            unknown=stage/'unknown'
            if nested:unknown.mkdir();unknown=unknown/'data'
            unknown.write_bytes(b'keep')
            with self.assertRaises(ValueError):cache.store(self.source,stage)
            self.assertEqual(unknown.read_bytes(),b'keep')
            self.assertFalse(cache.contains(self.source))

    def test_cancel_during_large_restoration_copy_removes_partial_session(self):
        cache=self.cache();(self.output/'seg000000.m4s').write_bytes(b'x'*(3*1024*1024))
        target=cache.store(self.source,self.output);stopped=threading.Event();original=Path.open
        class Reader:
            def __init__(self,stream):self.stream=stream
            def __enter__(self):return self
            def __exit__(self,*args):self.stream.close()
            def read(self,size):
                value=self.stream.read(size)
                if size>0:stopped.set()
                return value
        def opened(path,*args,**kw):
            stream=original(path,*args,**kw)
            return Reader(stream) if path==target/'seg000000.m4s' and args==('rb',) else stream
        # Validation finishes first; cancellation occurs while copying, not hashing.
        with patch.object(cache,'_validated',return_value=(target,cache._media_files(target))):
            with patch.object(Path,'open',opened):
                with self.assertRaises(EncodingCancelled):cache.restore(self.source,self.root/'partial',stopped.is_set)
        self.assertFalse((self.root/'partial').exists())

    def test_cleanup_failure_or_cancellation_preserves_ownership(self):
        from desktop_playable_cache import OWNER
        cache=self.cache();target=cache.store(self.source,self.output);original=Path.unlink
        def failing(path,*args,**kw):
            if path.name.endswith('.m4s'):raise OSError('blocked')
            return original(path,*args,**kw)
        with patch.object(Path,'unlink',failing):
            with self.assertRaises(OSError):cache._remove_owned(target)
        self.assertEqual((target/'owner.marker').read_text(encoding='ascii'),OWNER)
        stopped=threading.Event()
        def cancelling(path,*args,**kw):
            value=original(path,*args,**kw);stopped.set();return value
        with patch.object(Path,'unlink',cancelling):
            with self.assertRaises(EncodingCancelled):cache._remove_owned(target,stopped.is_set)
        self.assertEqual((target/'owner.marker').read_text(encoding='ascii'),OWNER)
        cache._remove_owned(target);self.assertFalse(target.exists())

    def test_future_hls_version_is_not_cached(self):
        cache=self.cache();playlist=self.output/'index.m3u8'
        playlist.write_text(playlist.read_text(encoding='utf-8').replace('#EXT-X-VERSION:7','#EXT-X-VERSION:999'),encoding='utf-8')
        with self.assertRaises(ValueError):cache.store(self.source,self.output)

if __name__=='__main__':unittest.main()
