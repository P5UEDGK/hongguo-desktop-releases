from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile,threading,unittest
from unittest.mock import patch
from desktop_range_cache import RangeDiskCache,preload,PreloadWorker
from desktop_stream import RangeReader


class RangeCacheTests(unittest.TestCase):
    def test_cache_close_flush_error_does_not_abort_teardown(self):
        cache=RangeDiskCache(self.path,100,100)
        cache.store(0,b'hello',lambda:False)
        with patch.object(cache.file,'close',side_effect=OSError('optional flush failed')):
            cache.close()
        self.assertTrue(cache.closed and cache.failed)
        self.assertTrue(cache.file.raw.closed)
        self.assertEqual(cache.entries,{})
        self.assertFalse(cache.snapshot()['cacheComplete'])
        cache.close()

    def test_interrupted_fill_restarts_after_backoff_without_duplicate_worker(self):
        class Source:
            size=65536*2;block_size=65536
            def __init__(self):self.calls=0
            def block(self,index,cancelled):
                self.calls+=1
                if self.calls==1:raise OSError('temporary disconnect')
                return b'x'*65536
            def reader(self,stopped,cache=None):return RangeReader(self,stopped,cache=cache)
        source=Source();cache=RangeDiskCache(self.path,source.size,source.size);self.addCleanup(cache.close)
        worker=PreloadWorker(source,cache,lambda:False)
        with patch('desktop_range_cache.time.monotonic',return_value=0):
            worker.tick();worker.thread.join(1)
            first=worker.thread;worker.tick();self.assertIs(worker.thread,first)
        with patch('desktop_range_cache.time.monotonic',return_value=1.1):
            worker.tick();worker.thread.join(1)
            self.assertIsNot(worker.thread,first);self.assertTrue(cache.snapshot()['cacheComplete'])
            finished=worker.thread;worker.tick();self.assertIs(worker.thread,finished)

    def test_worker_start_failure_is_explicit_and_can_retry(self):
        cache=RangeDiskCache(self.path,100,100);self.addCleanup(cache.close)
        worker=PreloadWorker(None,cache,lambda:False)
        with patch('desktop_range_cache.threading.Thread.start',side_effect=RuntimeError('unavailable')):
            worker.tick();self.assertEqual(worker.failure,'worker-start')
        worker.next_start=0
        with patch('desktop_range_cache.preload') as fill:
            worker.tick();worker.thread.join(1);fill.assert_called_once();self.assertIsNone(worker.failure)

    def test_restart_skips_cached_prefix_without_reading_payload(self):
        class Source:
            size=65536*4;block_size=65536
            def __init__(self):self.calls=[]
            def block(self,index,cancelled):self.calls.append(index);return b'x'*65536
            def reader(self,stopped,cache=None):return RangeReader(self,stopped,cache=cache)
        source=Source();cache=RangeDiskCache(self.path,source.size,source.size);self.addCleanup(cache.close)
        cache.store(0,b'x'*65536,lambda:False);cache.store(2,b'x'*65536,lambda:False)
        with patch.object(cache,'read',wraps=cache.read) as read:
            preload(source,cache,lambda:False)
        self.assertEqual(source.calls,[1,3]);self.assertEqual([c.args[0] for c in read.call_args_list],[1,3])
        self.assertTrue(cache.snapshot()['cacheComplete'])

    def test_close_retains_blocked_reader_until_it_actually_exits(self):
        entered,release,closed=threading.Event(),threading.Event(),threading.Event()
        cache=RangeDiskCache(self.path,100,100);self.addCleanup(cache.close)
        worker=PreloadWorker(None,cache,lambda:False)
        def blocked(*args):entered.set();release.wait(3)
        with patch('desktop_range_cache.preload',side_effect=blocked):
            worker.tick();self.assertTrue(entered.wait(1))
            closer=threading.Thread(target=lambda:(worker.close(),closed.set()));closer.start()
            try:self.assertFalse(closed.wait(1.1));self.assertTrue(worker.thread.is_alive())
            finally:release.set();closer.join(2)
        self.assertTrue(closed.is_set());self.assertFalse(worker.thread.is_alive())
        previous=worker.thread;worker.tick();self.assertIs(worker.thread,previous)

    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'cache'

    def test_fast_parallel_writes_reserve_exact_budget_and_do_not_overshoot(self):
        cache=RangeDiskCache(self.path,65536*4+3,65536*100);self.addCleanup(cache.close)
        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(lambda i:cache.store(i,b'x'*65536,lambda:False),range(100)))
        self.assertEqual(cache.snapshot()['cacheFileBytes'],65536*4)
        self.assertEqual(self.path.stat().st_size,65536*4)
        self.assertTrue(cache.snapshot()['preloadLimited'])
        self.assertFalse(cache.snapshot()['cacheComplete'])

    def test_cancel_close_and_duplicate_blocks_never_append_payload(self):
        cache=RangeDiskCache(self.path,100,100)
        cache.store(0,b'hello',lambda:True);self.assertEqual(self.path.stat().st_size,0)
        cache.store(0,b'hello',lambda:False);cache.store(0,b'bad',lambda:False)
        self.assertEqual(cache.read(0),b'hello');self.assertEqual(cache.snapshot()['cacheFileBytes'],5)
        cache.close();cache.store(1,b'x',lambda:False)
        self.assertIsNone(cache.read(0));self.assertEqual(self.path.stat().st_size,5)

    def test_fast_background_fill_replays_seek_without_network_and_stops_at_cap(self):
        class Source:
            size=65536*20;block_size=65536
            def __init__(self):self.calls=0
            def block(self,index,cancelled):self.calls+=1;return bytes([index])*65536
            def reader(self,stopped,cache=None):return RangeReader(self,stopped,cache=cache)
        for budget in (65536*20,65536*4):
            self.path.unlink(missing_ok=True);source=Source()
            cache=RangeDiskCache(self.path,budget,source.size)
            preload(source,cache,lambda:False)
            self.assertEqual(source.calls,budget//65536)
            with source.reader(lambda:False,cache=cache) as reader:
                reader.seek(65536*2+10);self.assertEqual(reader.read(20),bytes([2])*20)
            self.assertEqual(source.calls,budget//65536)
            self.assertEqual(cache.snapshot()['cacheComplete'],budget==source.size)
            self.assertLessEqual(self.path.stat().st_size,budget)
            cache.close()

    def test_optional_disk_failure_leaves_source_readable_and_incomplete(self):
        cache=RangeDiskCache(self.path,100,100);self.addCleanup(cache.close)
        with patch.object(cache.file,'write',side_effect=OSError('full')):
            cache.store(0,b'abc',lambda:False)
        self.assertTrue(cache.snapshot()['preloadLimited'])
        self.assertFalse(cache.snapshot()['cacheComplete']);self.assertIsNone(cache.read(0))
