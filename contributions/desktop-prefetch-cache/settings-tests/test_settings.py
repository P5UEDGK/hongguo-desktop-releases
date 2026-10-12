import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from desktop_cache_settings import CacheSettings, validate_ahead, validate_limit, clean_video_cache, make_router, default_application_cache_root
from fastapi import FastAPI
import requests
import socket
import threading
import time
import uvicorn


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='cache-settings-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.settings = CacheSettings(self.root/'data', self.root/'data')

    def test_default_uses_app_data_and_dedicated_folder(self):
        self.assertEqual(self.settings.load()['ahead'], 3)
        self.assertEqual(self.settings.load()['limitGB'], 10)
        work=self.root/'original-work'
        streams,session,custom=self.settings.startup_paths(work)
        self.assertEqual(streams,self.root/'data/video-cache/stream-cache')
        self.assertEqual(session.parent,self.root/'data/video-cache/playback-sessions')
        self.assertTrue(custom)
        self.assertEqual(self.settings.snapshot()['defaultDirectory'],str(self.root/'data/video-cache'))

    def test_values_strict(self):
        for value in [0,-1,True,False,3.0,'3',None,100001,[],{}]:
            with self.subTest(value=value), self.assertRaises(ValueError): validate_ahead(value)
        for value in [1,3,4,100000]: self.assertEqual(validate_ahead(value),value)
        self.assertIsNone(validate_ahead('all'))

    def test_product_default_is_independent_of_selected_cache(self):
        import os
        with patch.dict(os.environ,{'APPDATA':str(self.root/'windows-appdata'),'HONGGUO_DATA_DIR':''}):
            value=CacheSettings(self.root/'settings',default_application_cache_root())
            value.save({'directory':str(self.root/'other-drive'),'ahead':3})
            self.assertEqual(value.snapshot()['defaultDirectory'],str(self.root/'windows-appdata/cn.guoban.desktop-companion/video-cache'))

    def test_persistence_and_paths_with_chinese_spaces(self):
        target=self.root/'中文 缓存'
        value=self.settings.save({'directory':str(target),'ahead':'all'})
        self.assertTrue(value['restartRequired'])
        restored=CacheSettings(self.root/'data',self.root/'data')
        self.assertEqual(restored.load()['ahead'],'all')
        self.assertFalse(restored.snapshot()['restartRequired'])
        streams,work,custom=restored.startup_paths(self.root/'old')
        self.assertTrue(custom);self.assertEqual(streams,target/'video-cache/stream-cache')
        self.assertEqual(work.parent,target/'video-cache/playback-sessions')
        self.assertFalse(restored.path.read_bytes().startswith(b'\xef\xbb\xbf'))

    def test_failure_preserves_saved_config(self):
        self.settings.save({'directory':str(self.root/'cache'),'ahead':1})
        before=self.settings.path.read_bytes()
        file=self.root/'file';file.write_text('unrelated',encoding='utf8')
        for directory in ['relative',str(file)]:
            with self.assertRaises((ValueError,OSError)): self.settings.save({'directory':directory,'ahead':4})
            self.assertEqual(before,self.settings.path.read_bytes())
        with patch('desktop_cache_settings.os.replace',side_effect=OSError('read-only')):
            with self.assertRaises(OSError):self.settings.save({'directory':str(self.root/'other'),'ahead':4})
        self.assertEqual(before,self.settings.path.read_bytes())
        self.assertEqual(list(self.settings.path.parent.glob('.video-cache-settings-*')),[])

    def test_selected_root_is_contained_and_reset_is_portable(self):
        value=self.settings.save({'directory':str(self.root),'ahead':3,'limitGB':10})
        self.assertEqual(value['directory'],str(self.root/'video-cache'))
        again=self.settings.save({'directory':value['directory'],'ahead':3})
        self.assertEqual(again['directory'],value['directory'])
        reset=self.settings.save({'directory':value['defaultDirectory'],'ahead':3})
        self.assertEqual(reset['directory'],str(self.root/'data/video-cache'))

    def test_custom_unavailable_never_falls_back(self):
        self.settings.save({'directory':str(self.root/'cache'),'ahead':3})
        with patch('desktop_cache_settings.writable_directory',side_effect=PermissionError()):
            with self.assertRaises(PermissionError):self.settings.startup_paths(self.root/'old')

    def test_transient_windows_read_lock_is_bounded(self):
        self.settings.save({'directory':str(self.root/'cache'),'ahead':3})
        payload=self.settings.path.read_text(encoding='utf8')
        with patch.object(Path,'read_text',side_effect=[PermissionError(),payload]):
            self.assertEqual(self.settings.load()['ahead'],3)
        with patch.object(Path,'read_text',side_effect=PermissionError()) as read:
            with self.assertRaises(PermissionError):self.settings.load()
            self.assertEqual(read.call_count,3)

    def test_only_dead_marked_sessions_are_reaped(self):
        sessions=self.root/'sessions';sessions.mkdir()
        for name, marker in [('session-dead0000',{'owner':'hongguo-video-session-v1','pid':99999}),('session-live0000',{'owner':'hongguo-video-session-v1','pid':1}),('session-unknown0',{'owner':'other','pid':99999})]:
            child=sessions/name;child.mkdir();(child/'owner.json').write_text(json.dumps(marker),encoding='utf8')
        with patch.object(CacheSettings,'_process_alive',side_effect=lambda pid:pid==1):CacheSettings._reap_sessions(sessions)
        self.assertFalse((sessions/'session-dead0000').exists())
        self.assertTrue((sessions/'session-live0000').exists())
        self.assertTrue((sessions/'session-unknown0').exists())

    def test_live_callback_applies_after_atomic_save(self):
        calls=[]
        self.settings.prepare_change=lambda value:lambda:calls.append(self.settings.load())
        result=self.settings.save({'directory':str(self.root/'cache'),'ahead':4,'limitGB':2})
        self.assertEqual(calls[0]['limitGB'],2)
        self.assertFalse(result['restartRequired'])
        for value in [0,-1,True,1.2,'2']:
            with self.assertRaises(ValueError):validate_limit(value)

    def test_manual_cleanup_protects_active_and_unknown(self):
        import os
        from desktop_playable_cache import PlayableEpisodeCache
        root=self.root/'cache';root.mkdir()
        old=root/'10000001_desktopresolutionv1.mp4';old.write_bytes(b'a'*20)
        fresh=root/'10000002_desktopresolutionv1.mp4';fresh.write_bytes(b'b'*20)
        active=root/'10000003_desktopresolutionv1.mp4';active.write_bytes(b'c'*20)
        unknown=root/'my-file.txt';unknown.write_bytes(b'keep')
        os.utime(old,(1,1));os.utime(fresh,(2,2));os.utime(active,(0,0))
        cache=PlayableEpisodeCache(root/'.desktop-playable-v1',encoder=lambda *args:None, profile_files=(Path(__file__),))
        result=clean_video_cache(root,cache,protected=[active])
        self.assertFalse(old.exists());self.assertFalse(fresh.exists());self.assertTrue(active.exists());self.assertTrue(unknown.exists())
        self.assertEqual(result['clearedBytes'],40)
        result=clean_video_cache(root,cache,protected=[active])
        self.assertEqual(result['clearedBytes'],0)
        self.assertFalse(fresh.exists());self.assertTrue(active.exists());self.assertTrue(unknown.exists())

    def test_cleanup_api_and_invalid_limit(self):
        self.settings.clear_cache=lambda:{'clearedBytes':100,'clearedFiles':1,'remainingBytes':0}
        router=make_router(self.settings)
        endpoint=next(route.endpoint for route in router.routes if route.path.endswith('/clear'))
        self.assertEqual(endpoint()['clearedBytes'],100)
        with self.assertRaises(ValueError):self.settings.save({'directory':str(self.root/'cache'),'ahead':1,'limitGB':0})

    def test_cleanup_preserves_unknown_files_inside_owned_hls(self):
        from desktop_playable_cache import OWNER, PlayableEpisodeCache
        root=self.root/'cache';root.mkdir()
        cache=PlayableEpisodeCache(root/'.desktop-playable-v1',encoder=lambda *args:None,profile_files=(Path(__file__),))
        known=cache.root/('a'*64);known.mkdir()
        unknown=cache.root/('b'*64);unknown.mkdir()
        for entry in (known,unknown):
            (entry/'owner.marker').write_text(OWNER,encoding='ascii')
            (entry/'init.mp4').write_bytes(b'cache')
        (unknown/'notes.txt').write_bytes(b'keep')
        result=clean_video_cache(root,cache)
        self.assertFalse(known.exists())
        self.assertEqual((unknown/'notes.txt').read_bytes(),b'keep')
        self.assertTrue((unknown/'init.mp4').exists())
        self.assertEqual(result['clearedFiles'],1)

    def test_auth_origin_save_cancel(self):
        app=FastAPI();app.include_router(make_router(self.settings))
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(128);listener.setblocking(False)
        server=uvicorn.Server(uvicorn.Config(app,log_level='critical',access_log=False))
        thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
        client=requests.Session();client.trust_env=False
        try:
            deadline=time.monotonic()+5
            while not server.started and time.monotonic()<deadline:time.sleep(.01)
            self.assertTrue(server.started)
            base='http://127.0.0.1:'+str(listener.getsockname()[1])+'/desktop/cache-settings';headers={'origin':'http://tauri.localhost','x-desktop-cache-client':'1'}
            self.assertEqual(client.get(base).status_code,403)
            self.assertEqual(client.get(base,headers={'origin':'http://tauri.localhost'}).status_code,401)
            loaded=client.get(base,headers=headers).json();self.assertEqual(loaded['ahead'],3)
            self.assertEqual(client.post(base,headers=headers,json={'directory':str(self.root/'target'),'ahead':1}).status_code,401)
            headers['x-desktop-cache-token']=loaded['requestToken']
            response=client.post(base,headers=headers,json={'directory':str(self.root/'target'),'ahead':1})
            self.assertEqual(response.status_code,200)
            with patch.object(self.settings,'choose',return_value=None):
                self.assertIsNone(client.post(base+'/choose',headers=headers,json={}).json()['directory'])
            self.assertEqual(client.post(base,headers=headers,json={'directory':str(self.root/'target'),'ahead':0}).status_code,400)
        finally:
            client.close();server.should_exit=True;thread.join(5);listener.close()

if __name__=='__main__':unittest.main()
