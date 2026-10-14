import concurrent.futures
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from desktop_library import LibraryRelations, identity, make_router
from fastapi import FastAPI
from fastapi.testclient import TestClient

SID = '7673807696302197784'
OTHER = '7677914379060251673'
ALBUM = '7619198149772446782'


class Provider:
    def __init__(self):
        self.calls=[]
        self.data={sid:{'video_data':{'series_id':int(sid),'series_id_str':sid,
                   'series_title':'测试第九季','related_album_id':int(ALBUM),'season_index':9}}
                   for sid in (SID,OTHER)}

    def _episodes_body(self, value):
        return {'series_id':value}

    def api(self, method, path, **kwargs):
        ids=kwargs['body']['series_id'].split(',')
        self.calls.append((ids,kwargs.get('max_retries')))
        return {'code':0,'data':{sid:self.data[sid] for sid in ids if sid in self.data}}


class RelationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.provider=Provider()
        self.service=LibraryRelations(self.tmp.name,self.provider,lambda:1000)

    def test_persisted_cache_exact_ids_and_no_membership_tables(self):
        row=self.service.resolve([SID,SID])['relations'][0]
        self.assertEqual(row['albumId'],ALBUM)
        self.assertEqual(row['season'],9)
        restarted=LibraryRelations(self.tmp.name,self.provider)
        self.assertEqual(restarted.resolve([SID])['relations'][0],row)
        self.assertEqual(len(self.provider.calls),1)
        with restarted.connect() as db:
            tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(tables,{'relations','manual_groups'})

    def test_overlapping_requests_query_once(self):
        entered=threading.Event();release=threading.Event();original=self.provider.api
        def slow(*args,**kwargs):
            entered.set();release.wait(2);return original(*args,**kwargs)
        self.provider.api=slow
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            first=pool.submit(self.service.resolve,[SID]);self.assertTrue(entered.wait(1))
            second=pool.submit(self.service.resolve,[SID]);release.set()
            self.assertEqual(first.result(3),second.result(3))
        self.assertEqual(len(self.provider.calls),1)

    def test_batch_bound_and_failure_cooldown(self):
        ids=[str(9000000000000000000+n) for n in range(45)]
        rows=self.service.resolve(ids)['relations']
        self.assertEqual([len(call[0]) for call in self.provider.calls],[20,20,5])
        self.assertTrue(all(row['state']=='failed' and row['retryAt']==1300 for row in rows))
        self.service.resolve(ids)
        self.assertEqual(len(self.provider.calls),3)
        self.service.clock=lambda:1301
        self.service.resolve(ids)
        self.assertEqual(len(self.provider.calls),6)
        self.assertTrue(all(call[1]==1 for call in self.provider.calls))

    def test_missing_relation_and_mismatched_identity(self):
        del self.provider.data[SID]['video_data']['related_album_id']
        self.provider.data[OTHER]['video_data']['series_id_str']=SID
        rows=self.service.resolve([SID,OTHER])['relations']
        self.assertEqual(rows[0]['state'],'ungrouped')
        self.assertEqual(rows[0]['retryAt'],87400)
        self.assertEqual(rows[1]['state'],'failed')
        self.assertIsNone(rows[1]['albumId'])

    def test_manual_group_persists_and_can_be_undone(self):
        self.service.resolve([SID])
        value=self.service.set_manual(OTHER,SID)
        self.assertEqual(value['manual'][OTHER],'album:'+ALBUM)
        restarted=LibraryRelations(self.tmp.name,self.provider)
        self.assertEqual(restarted.snapshot()['manual'][OTHER],'album:'+ALBUM)
        self.assertNotIn(OTHER,restarted.set_manual(OTHER,None)['manual'])
        unknown='99990001'
        value=self.service.set_manual(OTHER,unknown)
        self.assertEqual(value['manual'][OTHER],value['manual'][unknown])

    def test_input_rejects_lossy_and_unbounded_ids(self):
        for ids in ([],[int(SID)],['../bad'],[SID]*101,None):
            with self.assertRaises(ValueError):self.service.resolve(ids)
        self.assertIsNone(identity(float(SID)))
        self.assertIsNone(identity(True))
        with self.assertRaises(ValueError):self.service.set_manual(SID,SID)

    def test_saved_relationship_fields(self):
        payload=json.loads((ROOT/'tests/fixtures/relationships.json').read_text(encoding='utf8'))
        self.provider.data=payload['data']
        rows=self.service.resolve(list(payload['data']))['relations']
        self.assertEqual(len(rows),7)
        self.assertTrue(all(row['state']=='resolved' for row in rows))
        group=[row for row in rows if row['albumId']==ALBUM]
        self.assertEqual(sorted(row['season'] for row in group),[9,10,11,13])

    def test_router_origin_session_and_validation(self):
        app=FastAPI();app.include_router(make_router(self.service))
        with TestClient(app) as client:
            self.assertEqual(client.get('/desktop/library').status_code,403)
            headers={'origin':'http://tauri.localhost','x-desktop-library-client':'1'}
            snapshot=client.get('/desktop/library',headers=headers)
            self.assertEqual(snapshot.status_code,200)
            self.assertEqual(client.post('/desktop/library/relations',headers=headers,json={'seriesIds':[SID]}).status_code,401)
            headers['x-desktop-library-token']=snapshot.json()['requestToken']
            value=client.post('/desktop/library/relations',headers=headers,json={'seriesIds':[SID]})
            self.assertEqual(value.status_code,200)
            self.assertEqual(value.json()['relations'][0]['albumId'],ALBUM)
            self.assertEqual(client.post('/desktop/library/relations',headers=headers,json={'seriesIds':[int(SID)]}).status_code,400)
            headers['origin']='https://example.org'
            self.assertEqual(client.post('/desktop/library/manual',headers=headers,json={'seriesId':OTHER,'targetId':SID}).status_code,403)


if __name__=='__main__':
    unittest.main()
