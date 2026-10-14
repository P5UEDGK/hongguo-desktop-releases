from pathlib import Path
import tempfile,threading,unittest
from desktop_cache_budget import CacheBudget,CacheLimitReached,cache_complete_episode


class BudgetTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve();self.stream=self.root/'stream-cache';self.stream.mkdir()
        self.limit=100000
        self.budget=CacheBudget(self.root,lambda:self.limit)
        self.calls=[]

    def write(self,path,maximum,check):
        self.calls.append(maximum);check();path.write_bytes(b'x'*maximum)

    def convert(self,source,output):
        self.assertFalse((self.stream/'10000001_desktopresolutionv1.mp4').exists())
        output.write_bytes(source.read_bytes())

    def store(self,size=100,fetch=None,convert=None):
        return cache_complete_episode(self.budget,self.stream/'10000001_desktopresolutionv1.mp4',size,fetch or self.write,convert or self.convert)

    def test_full_episode_published_after_complete_conversion(self):
        result=self.store()
        self.assertEqual(result.read_bytes(),b'x'*100)
        self.assertEqual(list(self.stream.iterdir()),[result])

    def test_episode_too_large_never_starts_and_keeps_existing_cache(self):
        old=self.stream/'old.mp4';old.write_bytes(b'keep')
        self.limit=65536+299
        with self.assertRaises(CacheLimitReached):self.store()
        self.assertEqual(self.calls,[]);self.assertEqual(old.read_bytes(),b'keep')
        self.assertEqual(list(self.stream.iterdir()),[old])

    def test_unknown_size_never_starts(self):
        for size in (0,-1,None,True):
            with self.subTest(size=size),self.assertRaises(CacheLimitReached):self.store(size)
        self.assertEqual(self.calls,[])

    def test_short_response_is_not_published(self):
        with self.assertRaises(OSError):self.store(fetch=lambda p,n,c:p.write_bytes(b'half'))
        self.assertEqual(list(self.stream.iterdir()),[])

    def test_oversized_response_is_not_published(self):
        with self.assertRaises(OSError):self.store(fetch=lambda p,n,c:p.write_bytes(b'x'*(n+1)))
        self.assertEqual(list(self.stream.iterdir()),[])

    def test_download_failure_leaves_no_half_episode(self):
        def fail(path,n,check):path.write_bytes(b'half');raise OSError('network')
        with self.assertRaises(OSError):self.store(fetch=fail)
        self.assertEqual(list(self.stream.iterdir()),[])

    def test_conversion_failure_leaves_no_half_episode(self):
        def fail(source,output):output.write_bytes(b'half');raise OSError('decode')
        with self.assertRaises(OSError):self.store(convert=fail)
        self.assertEqual(list(self.stream.iterdir()),[])

    def test_foreground_growth_and_hot_limit_deny_publication(self):
        def grows(source,output):
            output.write_bytes(b'complete');(self.root/'active-playback').write_bytes(b'a'*100001)
        with self.assertRaises(CacheLimitReached):self.store(convert=grows)
        self.assertFalse((self.stream/'10000001_desktopresolutionv1.mp4').exists())
        self.assertEqual((self.root/'active-playback').stat().st_size,100001)
        (self.root/'active-playback').unlink()
        def lower(source,output):output.write_bytes(b'complete');self.limit=1
        with self.assertRaises(CacheLimitReached):self.store(convert=lower)
        self.assertEqual(list(self.stream.iterdir()),[])

    def test_clear_or_limit_increase_allows_next_complete_episode(self):
        existing=self.root/'existing';existing.write_bytes(b'x'*99000)
        with self.assertRaises(CacheLimitReached):self.store()
        existing.unlink();self.assertTrue(self.store().exists())

    def test_admissions_are_serialized(self):
        entered=threading.Event();release=threading.Event();second=threading.Event()
        def first():
            with self.budget.admit(100):entered.set();release.wait(2)
        def next_one():
            with self.budget.admit(100):second.set()
        a=threading.Thread(target=first);a.start();self.assertTrue(entered.wait(1))
        b=threading.Thread(target=next_one);b.start();self.assertFalse(second.wait(.05))
        release.set();a.join(2);b.join(2);self.assertTrue(second.is_set())

    def test_unknown_content_counts_without_being_deleted(self):
        path=self.root/'notes.txt';path.write_bytes(b'x'*100000)
        with self.assertRaises(CacheLimitReached):self.store()
        self.assertEqual(path.stat().st_size,100000)

    def test_released_foreground_file_does_not_fail_capacity_scan(self):
        from unittest.mock import patch
        path=self.root/'released';path.write_bytes(b'video')
        original=Path.lstat
        def disappearing(item):
            if item==path:
                item.unlink()
                raise FileNotFoundError()
            return original(item)
        with patch.object(Path,'lstat',disappearing):self.assertEqual(self.budget.usage(),0)

    def test_output_outside_selected_folder_rejected(self):
        with self.assertRaises(ValueError):cache_complete_episode(self.budget,self.root/'outside.mp4',100,self.write,self.convert)

    def test_no_eviction_policy_keeps_owned_hls_when_full(self):
        from desktop_playable_cache import PlayableEpisodeCache,OWNER
        cache=PlayableEpisodeCache(self.root/'hls',encoder=lambda *a:None,quota_bytes=100,profile_files=(Path(__file__),),evict=False)
        entry=cache.root/('a'*64);entry.mkdir()
        (entry/'owner.marker').write_text(OWNER,encoding='ascii');(entry/'init.mp4').write_bytes(b'keep')
        with self.assertRaises(OSError):cache._reserve(100)
        self.assertEqual((entry/'init.mp4').read_bytes(),b'keep')

    def test_foreground_hls_plays_without_publishing_extra_cache_when_full(self):
        from desktop_playable_cache import PlayableEpisodeCache
        called=[]
        def deny():called.append(1);raise CacheLimitReached()
        def encode(source,directory,on_ready,**kwargs):
            directory.mkdir()
            (directory/'init.mp4').write_bytes(b'init')
            (directory/'seg000000.m4s').write_bytes(b'fragment')
            (directory/'index.m3u8').write_text('#EXTM3U\n#EXT-X-VERSION:7\n#EXT-X-TARGETDURATION:2\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:2,\nseg000000.m4s\n#EXT-X-ENDLIST\n',encoding='utf8')
            (directory/'complete.marker').write_text('desktop-hls-v1\n',encoding='ascii')
        source=self.root/'source.mp4';source.write_bytes(b'source')
        cache=PlayableEpisodeCache(self.root/'hls',encoder=encode,profile_files=(Path(__file__),),publish_check=deny,evict=False)
        output=self.root/'playing'
        cache.encode(source,output)
        self.assertTrue((output/'complete.marker').exists())
        self.assertEqual(list(cache.root.iterdir()),[])
        self.assertEqual(called,[1])
