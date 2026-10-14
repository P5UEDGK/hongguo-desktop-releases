"""Host integration: one bounded prefetch queue across a verified season boundary."""
import os,sys,unittest,tempfile,threading,uuid
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
BACKEND=Path(os.environ.get('HONGGUO_TEST_BACKEND',''))
if not (BACKEND/'desktop_prefetch.py').is_file():
    raise unittest.SkipTest('Set HONGGUO_TEST_BACKEND to the patched host backend')
sys.path.insert(0,str(BACKEND))
from desktop_prefetch import EpisodePrefetcher,PrefetchPaused
from desktop_hls_service import Job,HlsJobs,make_router
from desktop_season_playback import make_continuation_control
CUR,NEXT='8800000000000002001','8800000000000002002'
def episodes(base,count):return [{'index':n,'vid':str(base+n)} for n in range(1,count+1)]
A,B=episodes(10000000,3),episodes(20000000,4)
def output(directory):
    directory=Path(directory);directory.mkdir()
    (directory/'init.mp4').write_bytes(b'init')
    (directory/'seg000000.m4s').write_bytes(b'segment')
    (directory/'index.m3u8').write_text('#EXTM3U\n#EXT-X-VERSION:7\n#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:0\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:1,\nseg000000.m4s\n#EXT-X-ENDLIST\n',encoding='utf8')
    (directory/'complete.marker').write_text('desktop-hls-v1\n',encoding='ascii')
class CrossSeasonTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name);self.downloads=[];self.encodes=[];self.lookups=[]
        self.files={}
        for row in A+B:
            path=self.root/(row['vid']+'.mp4');path.write_bytes(('source-'+row['vid']).encode());self.files[row['vid']]=path
    def make(self,ahead=3,next_loader=None,download=None,current=None):
        def lookup(sid):self.lookups.append(sid);return NEXT,B
        def fetch(vid):self.downloads.append(vid);return self.files[vid]
        def encode(source,directory,on_ready=lambda:None,**kwargs):self.encodes.append(Path(source).stem);output(directory);on_ready()
        value=EpisodePrefetcher(lambda vid:self.files[vid],lambda sid:({},(current or A) if sid==CUR else B),self.root/uuid.uuid4().hex,
            encoder=encode,ahead=ahead,download_loader=download or fetch,next_season_loader=next_loader or lookup)
        self.addCleanup(value.close);return value
    def start(self,value,episode,mode='native'):
        job=Job(uuid.uuid4().hex,self.root/uuid.uuid4().hex,series_id=CUR,episode=episode,video_mode=mode)
        value.begin(job,CUR,episode);source=value.load_source(CUR,episode);return job,source
    def finish(self,value,job,source):
        if job.video_mode!='native':value.before_work(job);value.encode(source,job.directory,video_mode=job.video_mode)
        value.finish(job,CUR,job.episode,source)
    def targets(self,value):return [(r['seriesId'],r['episode']) for r in value.snapshot()['cacheTargets']]
    def test_penultimate_fills_three_with_current_tail_then_next_one_two(self):
        value=self.make();job,source=self.start(value,2);self.assertTrue(value.set_continuation(job,True));self.finish(value,job,source)
        self.assertTrue(value.wait_idle(3));self.assertEqual(self.targets(value),[(CUR,3),(NEXT,1),(NEXT,2)])
        self.assertEqual(self.downloads,['10000003','20000001','20000002']);self.assertEqual(len(self.lookups),1)
        self.assertEqual(value.latest_episodes,[(1,'10000001'),(2,'10000002'),(3,'10000003')])
    def test_last_prefetches_three_complete_artifacts_and_replay_hits_cache(self):
        value=self.make();job,source=self.start(value,3,'copy');value.set_continuation(job,True);self.finish(value,job,source)
        self.assertTrue(value.wait_idle(3));self.assertEqual(self.targets(value),[(NEXT,1),(NEXT,2),(NEXT,3)])
        self.assertEqual(self.downloads,['20000001','20000002','20000003']);self.assertEqual(self.encodes,['10000003','20000001','20000002','20000003'])
        next_source=self.files['20000001'];self.assertTrue(value.cache.contains(next_source,'copy'))
        value.cache.encoder=lambda *a,**k:(_ for _ in ()).throw(AssertionError('cache replay encoded again'))
        replay=self.root/'replay';value.encode(next_source,replay,video_mode='copy');self.assertTrue((replay/'complete.marker').is_file())
    def test_disabled_and_remaining_mode_do_not_lookup_next_season(self):
        for ahead in [3,None]:
            value=self.make(ahead);job,source=self.start(value,3)
            if ahead is None:value.set_continuation(job,True)
            self.finish(value,job,source);self.assertTrue(value.wait_idle(2));self.assertEqual(self.targets(value),[])
        self.assertEqual(self.lookups,[])
    def test_missing_first_episode_is_bounded_failure(self):
        calls=[]
        def lookup(sid):calls.append(sid);return NEXT,B[1:]
        value=self.make(next_loader=lookup);job,source=self.start(value,3);value.set_continuation(job,True);self.finish(value,job,source)
        self.assertTrue(value.wait_idle(2));value.set_continuation(job,True);self.assertTrue(value.wait_idle(2))
        self.assertEqual(calls,[CUR]);self.assertEqual(self.downloads,[])
    def test_short_next_season_never_recurses_into_another_season(self):
        calls=[]
        def lookup(sid):calls.append(sid);return NEXT,B[:1]
        value=self.make(next_loader=lookup);job,source=self.start(value,3);value.set_continuation(job,True);self.finish(value,job,source)
        self.assertTrue(value.wait_idle(2));self.assertEqual(self.targets(value),[(NEXT,1)]);self.assertEqual(calls,[CUR])
    def test_new_foreground_discards_late_metadata(self):
        entered,release=threading.Event(),threading.Event();self.addCleanup(release.set)
        def lookup(sid):entered.set();release.wait(3);return NEXT,B
        value=self.make(next_loader=lookup);job,source=self.start(value,3);value.set_continuation(job,True);self.finish(value,job,source)
        self.assertTrue(entered.wait(1));new,source=self.start(value,1);self.finish(value,new,source);release.set()
        self.assertTrue(value.wait_idle(3));self.assertEqual(self.targets(value),[(CUR,2),(CUR,3)]);self.assertFalse(any(v.startswith('2') for v in self.downloads))
    def test_turning_off_cannot_resurrect_a_capacity_paused_cross_task(self):
        entered,release=threading.Event(),threading.Event();self.addCleanup(release.set)
        def fetch(vid):self.downloads.append(vid);entered.set();release.wait(3);raise PrefetchPaused()
        value=self.make(download=fetch);job,source=self.start(value,3);value.set_continuation(job,True);self.finish(value,job,source)
        self.assertTrue(entered.wait(1));value.set_continuation(job,False);release.set();self.assertTrue(value.wait_idle(3))
        self.assertEqual(value.download_pending,[]);self.assertEqual(self.targets(value),[]);self.assertFalse(value.download_paused)
    def test_reenable_during_metadata_wait_restarts_only_after_old_request_finishes(self):
        entered,release=threading.Event(),threading.Event();self.addCleanup(release.set);calls=[]
        def lookup(sid):
            calls.append(sid)
            if len(calls)==1:entered.set();release.wait(3)
            return NEXT,B
        value=self.make(next_loader=lookup);job,source=self.start(value,3);value.set_continuation(job,True);self.finish(value,job,source)
        self.assertTrue(entered.wait(1));value.set_continuation(job,False);value.set_continuation(job,True);release.set()
        self.assertTrue(value.wait_idle(3));self.assertEqual(len(calls),2);self.assertEqual(self.downloads,['20000001','20000002','20000003'])
    def test_capacity_pause_resumes_with_hot_window_without_duplicate_metadata(self):
        capacity=[False]
        def fetch(vid):
            self.downloads.append(vid)
            if not capacity[0]:raise PrefetchPaused()
            return self.files[vid]
        value=self.make(download=fetch);job,source=self.start(value,3);value.set_continuation(job,True);self.finish(value,job,source)
        with value.condition:self.assertTrue(value.condition.wait_for(lambda:value.download_paused,2))
        capacity[0]=True;value.reconfigure(1);self.assertTrue(value.wait_idle(3));self.assertEqual(self.targets(value),[(NEXT,1)])
        self.assertEqual(self.downloads,['20000001','20000001']);self.assertEqual(len(self.lookups),1)
    def test_next_season_episode_one_failure_cannot_mark_current_episode_one_incomplete(self):
        value=self.make(current=A[:1]);job,source=self.start(value,1,'copy')
        original=value.cache.encoder
        def encode(source,directory,on_ready=lambda:None,**kwargs):
            if Path(source).stem=='20000001':raise OSError('next season failed')
            return original(source,directory,on_ready,**kwargs)
        value.cache.encoder=encode;value.set_continuation(job,True);self.finish(value,job,source)
        self.assertTrue(value.wait_idle(3));self.assertTrue(value.current_complete);self.assertEqual(value.snapshot()['failedEpisodes'],[2])
    def test_live_count_changes_during_metadata_lookup_use_latest_setting(self):
        entered,release=threading.Event(),threading.Event();self.addCleanup(release.set)
        def lookup(sid):self.lookups.append(sid);entered.set();release.wait(3);return NEXT,B
        value=self.make(next_loader=lookup);job,source=self.start(value,3);value.set_continuation(job,True);self.finish(value,job,source)
        self.assertTrue(entered.wait(1));value.reconfigure(1);release.set();self.assertTrue(value.wait_idle(3))
        self.assertEqual(self.downloads,['20000001']);self.assertEqual(len(self.lookups),1)
    def test_stale_or_standby_parent_cannot_control_current_queue(self):
        value=self.make();job,source=self.start(value,3);control=make_continuation_control(value)
        standby=Job('b'*32,self.root/'b',series_id=CUR,episode=3,prewarm_parent=job.id);standby.prefetch_generation=value.generation
        self.assertFalse(control(standby,True));job.prefetch_generation-=1;self.assertFalse(control(job,True));self.finish(value,job,source)
    def test_http_control_auth_revision_order_and_release(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        value=self.make();job,source=self.start(value,3);self.finish(value,job,source)
        directory=self.root/'jobs';directory.mkdir();jobs=HlsJobs(directory,lambda *a:source,on_continuation=make_continuation_control(value));self.addCleanup(jobs.close)
        jobs.jobs[job.id]=job;app=FastAPI();app.include_router(make_router(jobs,lambda key:key=='fixture'))
        url='/desktop/hls/'+job.id+'/continuation';headers={'x-api-key':'fixture','origin':'http://tauri.localhost'}
        with TestClient(app) as client:
            self.assertEqual(client.post(url,json={'enabled':True,'revision':2}).status_code,401)
            self.assertEqual(client.post(url,headers={**headers,'origin':'https://example.org'},json={'enabled':True,'revision':2}).status_code,403)
            self.assertEqual(client.post(url,headers=headers,json={'enabled':True,'revision':True}).status_code,400)
            self.assertTrue(client.post(url,headers=headers,json={'enabled':True,'revision':2}).json()['accepted'])
            self.assertFalse(client.post(url,headers=headers,json={'enabled':False,'revision':1}).json()['accepted'])
            self.assertTrue(value.continuation_enabled);jobs.release(job.id);self.assertFalse(value.continuation_enabled)
if __name__=='__main__':unittest.main(verbosity=2)
