"""Provider-independent routing and identity regressions; no live requests."""
import base64
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from desktop_video_resolver import VideoModelResolver, ModelUnavailable, media_urls


class EmptyResponse(RuntimeError):
    diagnostic = {"http_status": 200, "body_bytes": 0}


def entry(vid, **extra):
    return {"video_model": json.dumps({"video_id": vid, "video_list": {
        "video_1": {"main_url": "https://fixture.invalid/main"}}}), **extra}


class ResolverTests(unittest.TestCase):
    def make(self, handler):
        self.calls = []
        self.now = 1000.0
        def api(method, path, **kw):
            self.calls.append((path, kw))
            return handler(path, kw)
        return VideoModelResolver(api, empty_error=EmptyResponse,
                                  clock=lambda: self.now, wall=lambda: self.now)

    def test_batch_success_cache_copy_and_force(self):
        r = self.make(lambda p,k: {"data": {v:entry(v) for v in k['body']['mixed_video_id_map']['1']}})
        first = r.resolve(['1','1']); first['1']['video_id']='changed'
        self.assertEqual(r.resolve(['1'])['1']['video_id'],'1')
        self.assertEqual(len(self.calls),1)
        r.resolve(['1'],force=True)
        self.assertEqual(len(self.calls),2)

    def test_empty_fallback_cooldown_and_reprobe(self):
        def handler(path,kw):
            if path==VideoModelResolver.batch_path: raise EmptyResponse()
            return {'code':0,'data':entry(kw['body']['video_id'])}
        r=self.make(handler)
        self.assertEqual(set(r.resolve(['1','2'])),{'1','2'})
        self.assertEqual(len(self.calls),3)
        r.resolve(['3']); self.assertEqual(len(self.calls),4)
        self.now+=301
        r.resolve(['4']); self.assertEqual(len(self.calls),6)
        self.assertTrue(all(k['max_retries']==1 for _,k in self.calls))

    def test_partial_batch_only_requests_missing_id(self):
        r=self.make(lambda p,k: {'data':{'1':entry('1')}} if p==VideoModelResolver.batch_path
                    else {'data':entry(k['body']['video_id'])})
        self.assertEqual(set(r.resolve(['1','2'])),{'1','2'})
        self.assertEqual(self.calls[1][1]['body']['video_id'],'2')

    def test_auth_risk_transport_nonempty_and_429_do_not_fallback(self):
        for error in [PermissionError('auth'),RuntimeError('risk'),TimeoutError('transport')]:
            def handler(p,k): raise error
            r=self.make(handler)
            with self.assertRaises(type(error)): r.resolve(['1'])
            self.assertEqual(len(self.calls),1)
        for diagnostic in [{'http_status':429,'body_bytes':0},{'http_status':200,'body_bytes':10}]:
            e=EmptyResponse();e.diagnostic=diagnostic
            def handler(p,k): raise e
            r=self.make(handler)
            with self.assertRaises(EmptyResponse):r.resolve(['1'])
            self.assertEqual(len(self.calls),1)

    def test_wrong_episode_never_reused_and_single_failure_not_cached(self):
        r=self.make(lambda p,k:{'data':{'different':entry('different')}} if p==VideoModelResolver.batch_path
                    else {'data':{}})
        with self.assertRaises(ModelUnavailable):r.resolve(['1'])
        with self.assertRaises(ModelUnavailable):r.resolve(['1'])
        self.assertEqual(len(self.calls),3)
        self.assertFalse(r.cache)

    def test_vod_id_has_a_different_namespace_from_episode_id(self):
        r=self.make(lambda p,k:{'data':{'1':entry('vod-object-id')}})
        self.assertEqual(r.resolve(['1'])['1']['video_id'],'vod-object-id')

    def test_expiry_margin_and_cache_bound(self):
        r=self.make(lambda p,k:{'data':{v:entry(v,expire_time=self.now+70)
                            for v in k['body']['mixed_video_id_map']['1']}})
        r.max_entries=2
        r.resolve(['1']);self.now+=9;r.resolve(['1']);self.assertEqual(len(self.calls),1)
        self.now+=2;r.resolve(['1']);self.assertEqual(len(self.calls),2)
        r.resolve(['2','3']);self.assertEqual(len(r.cache),2)

    def test_concurrent_same_id_has_one_request(self):
        gate=threading.Event();started=threading.Event()
        def handler(p,k):
            started.set();gate.wait(2);return {'data':{'1':entry('1')}}
        r=self.make(handler)
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures=[pool.submit(r.resolve,['1']) for _ in range(4)]
            self.assertTrue(started.wait(2));gate.set()
            for f in futures:self.assertIn('1',f.result(3))
        self.assertEqual(len(self.calls),1)

    def test_backups_ordered_and_deduplicated(self):
        self.assertEqual(media_urls({'main_url':'main','backup_url_2':'b2',
            'backup_url_1':'b1','backup_url':'b1','backup_url_other':'bad'}),['main','b1','b2'])

    def test_expired_model_and_explicit_denial_are_not_fallback_success(self):
        for response in [{'code':429,'data':{}},
                         {'data':{'1':entry('1',expire_time=999)}}]:
            r=self.make(lambda p,k:response)
            with self.assertRaises(ModelUnavailable):r.resolve(['1'])
            self.assertEqual(len(self.calls),1)


if __name__=='__main__': unittest.main()
