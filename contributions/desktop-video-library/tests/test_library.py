from pathlib import Path
import json
import tempfile
import threading
import unittest
from unittest.mock import patch

from desktop_cache_budget import CacheBudget, cache_complete_episode, CacheLimitReached
from desktop_cache_settings import clean_video_cache
from desktop_playable_cache import PlayableEpisodeCache
from desktop_video_library import VideoLibrary, safe_name, series_names

SID='1234567890123456'
VID='10000001'


class VideoLibraryTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name).resolve();self.stream=self.root/'stream-cache';self.stream.mkdir()
        self.library=VideoLibrary(self.stream)
        self.budget=CacheBudget(self.root,lambda:1000000)
        self.library.register(SID,{'title':'中文剧名 第二季'},[{'index':1,'vid':VID},{'index':2,'vid':'10000002'}])

    def store(self,vid=VID,payload=b'complete video',convert=None):
        output=self.library.target(vid)
        return cache_complete_episode(self.budget,output,len(payload),lambda p,n,c:p.write_bytes(payload),
            convert or (lambda source,dest:dest.write_bytes(source.read_bytes())),
            before_publish=lambda staged,out:self.library.prepare_publish(vid,staged,out))

    def test_complete_named_original_and_persistent_lookup(self):
        path=self.store()
        self.assertEqual(path.relative_to(self.stream).as_posix(),f'中文剧名 [{SID}]/第02季/中文剧名_第02季_第001集.mp4')
        self.assertEqual(VideoLibrary(self.stream).lookup(VID),path)
        self.assertEqual(path.read_bytes(),b'complete video')
        self.assertNotIn('url',self.library.path.read_text(encoding='utf8'))
        self.assertFalse(self.library.path.read_bytes().startswith(b'\xef\xbb\xbf'))

    def test_season_fallback_and_explicit_metadata(self):
        self.assertEqual(series_names({'title':'短剧'}),('短剧','未分季'))
        self.assertEqual(series_names({'title':'短剧第十二季'}),('短剧','第12季'))
        self.assertEqual(series_names({'title':'短剧第1000季'}),('短剧第1000季','未分季'))
        self.assertEqual(series_names({'title':'短剧','season_number':3}),('短剧','第03季'))
        self.assertEqual(series_names({'title':'短剧','season_number':True}),('短剧','未分季'))

    def test_windows_invalid_reserved_and_empty_names(self):
        self.assertEqual(safe_name('CON'),'_CON')
        self.assertEqual(safe_name('NUL.mp4'),'_NUL.mp4')
        self.assertEqual(safe_name(' ../中文:*?\\剧名. '),'_中文____剧名')
        self.assertEqual(safe_name('...'),'未命名短剧')
        self.assertLessEqual(len(safe_name('长剧名'*100)),36)

    def test_same_title_series_do_not_collide(self):
        first=self.library.target(VID)
        self.library.register('1234567890123457',{'title':'中文剧名 第二季'},[{'index':1,'vid':'10000003'}])
        self.assertNotEqual(first.parent,self.library.target('10000003').parent)

    def test_unknown_same_name_file_is_not_overwritten(self):
        normal=self.library.target(VID);normal.write_bytes(b'user data')
        output=self.store()
        self.assertTrue(output.stem.endswith('_'+VID))
        self.assertEqual(normal.read_bytes(),b'user data')
        output.unlink();output.write_bytes(b'unknown replacement')
        with self.assertRaises(FileExistsError):self.store()
        self.assertEqual(output.read_bytes(),b'unknown replacement')

    def test_failed_or_partial_media_has_no_record_or_published_half(self):
        def fail(source,output):output.write_bytes(b'half');raise OSError('decode')
        with self.assertRaises(OSError):self.store(convert=fail)
        self.assertIsNone(self.library.lookup(VID))
        self.assertEqual(list(self.stream.rglob('*.mp4')),[])
        self.assertEqual(list(self.stream.rglob('.episode-*')),[])

    def test_index_failure_prevents_media_publication(self):
        with patch('desktop_video_library.os.replace',side_effect=OSError('index locked')):
            with self.assertRaises(OSError):self.store()
        self.assertIsNone(self.library.lookup(VID))
        self.assertEqual(list(self.stream.rglob('*.mp4')),[])

    def test_crash_between_index_and_media_is_not_a_cache_hit(self):
        output=self.library.target(VID);stage=self.root/'stage';stage.write_bytes(b'complete')
        self.library.prepare_publish(VID,stage,output)
        self.assertIsNone(VideoLibrary(self.stream).lookup(VID))
        self.assertEqual(self.store().read_bytes(),b'complete video')

    def test_replaced_or_modified_original_not_trusted_or_cleaned(self):
        path=self.store();path.write_bytes(b'changed video!')
        self.assertIsNone(self.library.lookup(VID))
        self.assertIsNone(VideoLibrary(self.stream).lookup(VID))
        self.assertEqual(self.clean()['clearedBytes'],0)
        self.assertTrue(path.exists())

    def clean(self,**kwargs):
        cache=PlayableEpisodeCache(self.stream/'.desktop-playable-v1',encoder=lambda *a:None,profile_files=(Path(__file__),))
        return clean_video_cache(self.stream,cache,library=self.library,**kwargs)

    def test_clean_nested_originals_protects_active_and_unknown(self):
        first=self.store();second=self.store('10000002')
        unknown=first.parent/'notes.txt';unknown.write_bytes(b'keep')
        result=self.clean(protected=[first])
        self.assertEqual(result['clearedBytes'],len(b'complete video'))
        self.assertFalse(second.exists());self.assertTrue(first.exists());self.assertTrue(unknown.exists())
        self.assertIsNone(VideoLibrary(self.stream).lookup('10000002'))
        self.clean();self.assertTrue(unknown.exists())

    def test_cleanup_removes_only_empty_named_directories(self):
        path=self.store();self.clean()
        self.assertFalse(path.parent.exists());self.assertFalse(path.parent.parent.exists())
        self.assertTrue(self.stream.exists());self.assertTrue(self.library.path.exists())

    def test_nested_capacity_counts_all_bytes_and_refuses_large_episode(self):
        self.store();before=self.budget.usage();self.assertGreater(before,len(b'complete video'))
        self.budget.limit_bytes=lambda:before
        with self.assertRaises(CacheLimitReached):self.store('10000002')
        self.assertIsNone(self.library.lookup('10000002'));self.assertIsNotNone(self.library.lookup(VID))

    def test_corrupt_or_path_injected_index_is_preserved(self):
        self.store();value=json.loads(self.library.path.read_text(encoding='utf8'))
        value['files'][VID]['relative']='../../outside.mp4'
        self.library.path.write_text(json.dumps(value),encoding='utf8')
        with self.assertRaises(OSError):VideoLibrary(self.stream)
        with self.assertRaises(OSError):self.library.register(SID,{'title':'新标题'},[{'index':1,'vid':VID}])
        self.assertEqual(json.loads(self.library.path.read_text(encoding='utf8')),value)

    def test_linked_named_directory_is_rejected(self):
        outside=self.root/'outside';outside.mkdir()
        parent=self.stream/f'中文剧名 [{SID}]'
        try:parent.symlink_to(outside,target_is_directory=True)
        except OSError:self.skipTest('Symlink creation is not available')
        with self.assertRaises(OSError):self.library.target(VID)
        self.assertEqual(list(outside.iterdir()),[])

    def test_concurrent_series_registration_and_publication_keeps_both_records(self):
        failures=[]
        def write(vid):
            try:self.store(vid)
            except Exception as exc:failures.append(exc)
        threads=[threading.Thread(target=write,args=(vid,)) for vid in (VID,'10000002')]
        for thread in threads:thread.start()
        for thread in threads:thread.join(5);self.assertFalse(thread.is_alive())
        self.assertEqual(failures,[])
        restored=VideoLibrary(self.stream)
        self.assertIsNotNone(restored.lookup(VID));self.assertIsNotNone(restored.lookup('10000002'))



if __name__=='__main__':unittest.main()
