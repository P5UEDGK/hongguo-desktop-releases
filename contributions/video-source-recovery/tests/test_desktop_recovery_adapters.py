"""Execute the real host functions without starting the application/server."""
import ast
import base64
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
import unittest
from desktop_video_resolver import VideoModelResolver, media_urls


class EmptyResponse(RuntimeError):
    diagnostic={'http_status':200,'body_bytes':0}


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.backend=Path(os.environ.get('RECOVERY_BACKEND',Path(__file__).resolve().parents[1]/'backend'))
        self.calls=[]
        self.model={'video_id':'vod-id','video_list':{'t':{
            'main_url':base64.b64encode(b'https://main.invalid/x').decode(),
            'backup_url_1':base64.b64encode(b'https://backup.invalid/x').decode(),
            'size':100,'definition':'1080p','encrypt':True,'spade_a':'fixture'}}}
        def api(method,path,**kw):
            self.calls.append(path)
            if path==VideoModelResolver.batch_path:raise EmptyResponse()
            return {'code':0,'data':{'video_model':json.dumps(self.model)}}
        self.resolver=VideoModelResolver(api,empty_error=EmptyResponse)
        self.h=SimpleNamespace(api=api,get_video_models=self.resolver.resolve,media_urls=media_urls)
        self.ns={'H':self.h,'json':json,'api':api,
                 'SG':SimpleNamespace(cache_get=lambda _:None,cache_key=lambda *a:a)}
    def function(self,file,name):
        tree=ast.parse((self.backend/file).read_text(encoding='utf-8'))
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(self.backend/file),'exec'),self.ns)
        return self.ns[name]
    def test_original_failure_now_resolves_through_actual_download_adapter(self):
        load=self.function('offline_dl.py','_video_model')
        self.assertEqual(load('episode-id'),self.model)
        self.assertEqual(load('episode-id'),self.model)
        self.assertEqual(self.calls,[VideoModelResolver.batch_path,VideoModelResolver.single_path])
    def test_provider_numbered_backups_normalized_without_metadata_loss(self):
        tracks=self.function('hongguo.py','video_model_tracks')(self.model)
        self.assertEqual(tracks[0]['backup_url_1'],'https://backup.invalid/x')
        self.assertEqual(tracks[0]['encrypt_info']['spade_a'],'fixture')
        self.assertEqual(tracks[0]['video_meta']['size'],100)
    def test_actual_public_tracks_and_urls_share_cache(self):
        self.ns['get_video_models']=self.h.get_video_models
        self.function('hongguo.py','video_model_tracks')
        get_tracks=self.function('hongguo.py','get_video_tracks')
        self.ns['media_urls']=media_urls
        get_urls=self.function('hongguo.py','get_video_urls')
        self.assertTrue(get_tracks(['episode-id']))
        self.assertEqual(get_urls(['episode-id'])['episode-id']['backup'],'https://backup.invalid/x')
        self.assertEqual(len(self.calls),2)
    def test_server_passes_candidates_from_selected_track(self):
        tracks=self.function('hongguo.py','video_model_tracks')(self.model)
        self.h.video_model_tracks=lambda _:tracks
        self.ns['ODL']=SimpleNamespace(_video_model=lambda _:self.model,
            _pick_track=lambda ts,q:(ts[0],'1080p',None))
        tr=self.function('server.py','_vm_track')('episode-id')
        self.assertEqual(tr['backup_urls'],['https://backup.invalid/x'])
        self.assertEqual(tr['size'],100)

    def test_catalog_date_helper_keeps_its_module_imports(self):
        tree=ast.parse((self.backend/'hongguo.py').read_text(encoding='utf-8'))
        imports=[n for n in tree.body if isinstance(n,ast.Import)
                 and any(a.name=='datetime' for a in n.names)]
        exec(compile(ast.Module(body=imports,type_ignores=[]),'imports','exec'),self.ns)
        self.assertTrue(self.function('hongguo.py','_is_today_ts')(time.time()))


if __name__=='__main__':unittest.main()
