"""Optional host integration tests; use the existing patched relationship owner."""
import concurrent.futures,io,os,sys,tempfile,threading,unittest
from pathlib import Path
from PIL import Image
from desktop_posters import PosterCache
host=os.environ.get('HONGGUO_HOST_BACKEND')
if host:
    sys.path.insert(0,host)
    from desktop_library import LibraryRelations
SID='9000000000000001';OTHER='9000000000000002';URL='https://fqnovelpic.com/fixture.jpg'
def picture():
    out=io.BytesIO();Image.new('RGB',(30,40),'red').save(out,'JPEG');return out.getvalue()
class Provider:
    def _episodes_body(self,value):return {'series_id':value}
    def api(self,*args,**kwargs):
        return {'code':0,'data':{sid:{'video_data':{'series_id_str':sid,'series_title':'人工图片验收',
          'related_album_id':'9000000000000099','season_index':1,'series_cover':URL}}
          for sid in kwargs['body']['series_id'].split(',')}}
@unittest.skipUnless(host,'Set HONGGUO_HOST_BACKEND to the patched host backend directory')
class HostCoverTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.provider=Provider();self.cache=PosterCache(self.tmp.name,lambda url:picture())
        self.service=LibraryRelations(self.tmp.name,self.provider,posters=self.cache)
    def test_known_cover_url_does_not_wait_for_unrelated_metadata_lock(self):
        self.service.resolve([SID])
        entered=threading.Event();release=threading.Event();original=self.provider.api
        def slow(*args,**kwargs):
            entered.set();release.wait(3);return original(*args,**kwargs)
        self.provider.api=slow
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            background=pool.submit(self.service.resolve,[OTHER]);self.assertTrue(entered.wait(1))
            try:
                cover=pool.submit(self.service.covers,[SID])
                self.assertIn(SID,cover.result(1)['covers'])
                self.assertFalse(background.done())
            finally:release.set()
            background.result(4)

    def test_known_cover_streams_before_same_batch_missing_metadata(self):
        self.service.resolve([SID])
        entered=threading.Event();release=threading.Event();original=self.provider.api
        def slow(*args,**kwargs):
            entered.set();release.wait(3);return original(*args,**kwargs)
        self.provider.api=slow
        updates=self.service.cover_updates([SID,OTHER]);self.assertEqual(next(updates)['covers'],{})
        with concurrent.futures.ThreadPoolExecutor(1) as pool:
            fast=pool.submit(next,updates)
            try:
                self.assertEqual(list(fast.result(1)['covers']),[SID])
                self.assertTrue(entered.wait(1));self.assertFalse(self.cache.path(OTHER).exists())
            finally:
                release.set();fast.result(4);remaining=list(updates)
        self.assertEqual(len(remaining),1);self.assertEqual(list(remaining[0]['covers']),[OTHER])
