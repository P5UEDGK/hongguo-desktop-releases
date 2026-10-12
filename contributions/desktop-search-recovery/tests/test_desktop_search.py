import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from desktop_search import DesktopSearch, make_router, upstream_get
from fastapi import FastAPI
from fastapi.testclient import TestClient


def response(sid='7694116863835376664', more=True, offset=20):
    return {'code':0,'data':{'search_data':[{'books':[{'book_id':sid,'book_name':'谁说没灵根不能修仙的？',
             'chapter_number':'116'}]}] if sid else [],'has_more':more,'next_offset':offset,'search_id':'session','tab_type':13}}


class SearchTests(unittest.TestCase):
    def test_get_wire_contract(self):
        class Reply:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def raise_for_status(self):pass
            def iter_content(self,size):yield b'{"code":0}'
        with patch('desktop_search.requests.request', return_value=Reply()) as call:
            params={'query':'中文 & ?','tab_type':13}
            self.assertEqual(upstream_get(params,call),{'code':0})
            self.assertEqual(call.call_args.args[0],'GET')
            self.assertEqual(call.call_args.kwargs['params'],params)
            self.assertNotIn('json',call.call_args.kwargs)
            self.assertNotIn('data',call.call_args.kwargs)

    def test_pagination_and_replay(self):
        calls=[]
        def request(params):
            calls.append(params)
            return response() if params['offset']==0 else response('7694116863835376665',False,40)
        service=DesktopSearch(request)
        first=service.page(' 谁说没灵根 ',1,'manju')
        second=service.page('谁说没灵根',2,'manju')
        self.assertEqual(service.page('谁说没灵根',2,'manju'),second)
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[1]['search_id'],'session')
        self.assertEqual(calls[1]['offset'],20)
        self.assertEqual(second['retrievedCount'],2)
        self.assertFalse(second['hasMore'])
        self.assertEqual(first['items'][0]['episodeCount'],116)
        self.assertEqual(first['items'][0]['source'],'novelfm')  # Activates the existing persistent poster loader.
        with self.assertRaises(ValueError):service.page('谁说没灵根',3,'manju')

    def test_transient_failure_retry_is_bounded(self):
        class Reply:
            def __init__(self, code):self.code=code
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def raise_for_status(self):pass
            def iter_content(self,size):yield ('{"code":%d}'%self.code).encode()
        with patch('desktop_search.time.sleep'),patch('desktop_search.requests.request',side_effect=[Reply(6000),Reply(0)]) as call:
            self.assertEqual(upstream_get({},call)['code'],0)
            self.assertEqual(call.call_count,2)
        with patch('desktop_search.time.sleep'),patch('desktop_search.requests.request',side_effect=[Reply(6000),Reply(6000)]) as call:
            self.assertEqual(upstream_get({},call)['code'],6000)
            self.assertEqual(call.call_count,2)

    def test_modes(self):
        calls=[]
        def request(params):
            calls.append(params)
            payload=response(more=False)
            payload['data']['tab_type']=params['tab_type']
            return payload
        service=DesktopSearch(request)
        service.page('a',1,'short');service.page('a',1,'manju')
        self.assertEqual([p['tab_type'] for p in calls],[10,13])
        self.assertTrue(all(p['limit']==20 and p['aid']=='3040' for p in calls))

    def test_failed_response_never_empty_success(self):
        bad=[{'code':6000,'data':{}},{'code':False,'data':{}}, {'code':0,'data':{}},
             response(sid=None),response(more=True,offset=0)]
        for field,value in [('has_more',None),('search_id',''),('tab_type',10)]:
            item=response();item['data'][field]=value;bad.append(item)
        item=response();item['data']['search_data'][0]['books'][0]['book_id']='bad';bad.append(item)
        for payload in bad:
            with self.subTest(payload=payload),self.assertRaises(ValueError):
                DesktopSearch(lambda p:payload).page('a',1,'manju')

    def test_empty_last_page(self):
        result=DesktopSearch(lambda p:response(sid=None,more=False)).page('a',1,'manju')
        self.assertEqual(result['items'],[])
        self.assertFalse(result['hasMore'])

    def test_duplicate_and_failed_page_retry(self):
        replies=iter([response(),{'code':6000},response(),response('7694116863835376665',False)])
        service=DesktopSearch(lambda p:next(replies))
        service.page('a',1,'manju')
        with self.assertRaisesRegex(ValueError,'成功'):service.page('a',2,'manju')
        with self.assertRaisesRegex(ValueError,'重复'):service.page('a',2,'manju')
        self.assertEqual(service.page('a',2,'manju')['retrievedCount'],2)

    def test_expiry_capacity_and_input(self):
        now=[0]
        service=DesktopSearch(lambda p:response(),clock=lambda:now[0],ttl=1,capacity=1)
        service.page('a',1,'manju');service.page('b',1,'manju')
        self.assertEqual(len(service.states),1)
        now[0]=2
        with self.assertRaisesRegex(ValueError,'过期'):service.page('b',2,'manju')
        for args in [('a',True,'manju'),('',1,'manju'),('a',1,'bad'),('a',0,'short')]:
            with self.subTest(args=args),self.assertRaises(ValueError):service.page(*args)

    def test_http_boundary_and_error(self):
        app=FastAPI()
        service=DesktopSearch(lambda p:{'code':6000})
        app.include_router(make_router(service))
        headers={'origin':'http://tauri.localhost','x-desktop-search-client':'1'}
        with TestClient(app,client=('127.0.0.1',50000)) as client:
            self.assertEqual(client.get('/desktop/search').status_code,403)
            self.assertEqual(client.get('/desktop/search',headers={'origin':headers['origin']}).status_code,401)
            token=client.get('/desktop/search',headers=headers).json()['requestToken']
            body={'query':'a','page':1,'mode':'manju'}
            self.assertEqual(client.post('/desktop/search',headers=headers,json=body).status_code,401)
            headers['x-desktop-search-token']=token
            result=client.post('/desktop/search',headers=headers,json=body)
            self.assertEqual(result.status_code,502)
            self.assertIn('成功状态',result.json()['detail'])


if __name__=='__main__':unittest.main()
