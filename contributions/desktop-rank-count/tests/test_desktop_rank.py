import copy
import json
import socket
import sys
import threading
import time
import unittest
from concurrent.futures import Future, ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from desktop_rank import DesktopRank, RankTransport, parse_page, make_router
from fastapi import HTTPException, Request


def upstream_page(board,page,client_factory=None):
    transport=RankTransport(client_factory)
    try:return transport.page(board,page)
    finally:transport.close()


def content():
    return {'isSuccess': True, 'rankList': [
        {'seriesId': '7690195777649380414', 'title': '爆笑姐妹',
         'episodeVids': [str(7690281396031458328 + i) for i in range(162)],
         'description': '简介', 'tags': ['穿越'], 'heatText': '热度', 'cover': 'cover'}],
        'pagination': {'pageNum': 1, 'totalPages': 5}}


def payload(value=None, page=1, deferred=True):
    value = content() if value is None else value
    head = {'pageNum': page, 'content': '__deferred_promise:content' if deferred else value}
    return json.dumps(head) + ('\n\ndata:' + json.dumps({'content': value}) if deferred else '')


class RankTests(unittest.TestCase):
    def test_inline_and_deferred_same_result(self):
        actual = parse_page(payload(), 1)
        self.assertEqual(actual, parse_page(payload(deferred=False), 1))
        self.assertEqual(actual[0]['episodeCount'], 162)
        self.assertEqual(actual[0]['tags'], ['穿越'])
        self.assertEqual(actual[0]['hotText'], '热度')
        self.assertEqual(actual, parse_page(payload().replace('\n', '\r\n'), 1))

    def test_redacted_official_samples(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/rank-samples.json').read_text(encoding='utf8'))
        first=parse_page(json.dumps(fixture['page1']),1)
        second=parse_page(json.dumps(fixture['page2']),2)
        self.assertEqual([row['episodeCount'] for row in first],[540,162])
        self.assertEqual([row['episodeCount'] for row in second],[150,112])
        self.assertEqual(second[0]['seriesId'],'7691698632214449177')

    def test_incomplete_and_error_frames_are_rejected(self):
        values = [payload().split('\n\n')[0], payload()+'\n\nerror:{}',
                  payload()+'\n\ndata:'+json.dumps({'content':content()}),
                  '<html></html>', '{}', '[]', payload(page=2)]
        for value in values:
            with self.subTest(value=value[:60]), self.assertRaises(ValueError):
                parse_page(value, 1)

    def test_invalid_identity_and_partial_lists_are_rejected(self):
        for modify in [lambda x:x['rankList'][0].update(seriesId='bad'),
                       lambda x:x['rankList'][0].update(episodeVids=[]),
                       lambda x:x['rankList'][0].pop('episodeVids'),
                       lambda x:x['rankList'][0].update(episodeVids=['12345678']*2),
                       lambda x:x['rankList'][0].update(episodeVids=[True]),
                       lambda x:x['rankList'].append(copy.deepcopy(x['rankList'][0])),
                       lambda x:x.update(isSuccess=False),
                       lambda x:x['pagination'].update(pageNum=2)]:
            value=content();modify(value)
            with self.assertRaises(ValueError):parse_page(payload(value), 1)

    def test_single_request_cache_refresh_and_expiry(self):
        calls=[];now=[0]
        service=DesktopRank(lambda board,page:(calls.append((board,page)) or payload()),clock=lambda:now[0],ttl=10)
        for _ in range(3):self.assertEqual(service.page('hot',1)[0]['episodeCount'],162)
        self.assertEqual(len(calls),1)
        service.page('hot',1,True);self.assertEqual(len(calls),2)
        now[0]=11;service.page('hot',1);self.assertEqual(len(calls),3)

    def test_concurrent_load_is_coalesced(self):
        started=threading.Event();release=threading.Event();calls=[]
        def request(board,page):
            calls.append((board,page));started.set();release.wait(5);return payload()
        service=DesktopRank(request)
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs=[pool.submit(service.page,'hot',1) for _ in range(4)]
            self.assertTrue(started.wait(2));release.set()
            self.assertTrue(all(job.result()[0]['episodeCount']==162 for job in jobs))
        self.assertEqual(calls,[('hot',1)])

    def test_failed_refresh_preserves_good_cache_and_no_retry(self):
        calls=[]
        def request(board,page):
            calls.append(1)
            if len(calls)>1:raise ValueError('failure')
            return payload()
        service=DesktopRank(request);service.page('hot',1)
        with self.assertRaises(ValueError):service.page('hot',1,True)
        self.assertEqual(service.page('hot',1)[0]['episodeCount'],162)
        self.assertEqual(len(calls),2)

    def test_concurrent_failures_share_one_load_and_next_call_recovers(self):
        started=threading.Event();release=threading.Event();joined=threading.Event()
        joined_lock=threading.Lock();waiters=[0];calls=[]
        class ObservedFuture(Future):
            def result(self,*args,**kwargs):
                with joined_lock:
                    waiters[0]+=1
                    if waiters[0]==3:joined.set()
                return super().result(*args,**kwargs)
        def request(board,page):
            calls.append((board,page))
            if len(calls)==1:
                started.set();release.wait(5);raise ValueError('shared failure')
            return payload()
        with patch('desktop_rank.Future',ObservedFuture,create=True):
            service=DesktopRank(request)
            with ThreadPoolExecutor(max_workers=4) as pool:
                jobs=[pool.submit(service.page,'hot',1) for _ in range(4)]
                try:
                    self.assertTrue(started.wait(2))
                    self.assertTrue(joined.wait(.5),'waiting requests must join the same load')
                finally:release.set()
                for job in jobs:
                    with self.assertRaisesRegex(ValueError,'shared failure'):job.result()
            self.assertEqual(calls,[('hot',1)])
            self.assertEqual(service.page('hot',1)[0]['episodeCount'],162)
            self.assertEqual(len(calls),2)

    def test_total_deadline_interrupts_slow_stream_before_one_chunk_completes(self):
        class SlowBody(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200);self.send_header('Content-Length','100');self.end_headers()
                try:
                    for _ in range(100):
                        self.wfile.write(b'x');self.wfile.flush();time.sleep(.03)
                except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),SlowBody)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with patch('desktop_rank.BASE',f'http://127.0.0.1:{server.server_port}'),patch('desktop_rank.TOTAL_SECONDS',.2,create=True):
                started=time.monotonic()
                with self.assertRaisesRegex(ValueError,'超时'):upstream_page('hot',1)
                self.assertLess(time.monotonic()-started,1)
        finally:server.shutdown();server.server_close();thread.join(2)

    def test_total_deadline_interrupts_slow_status_and_headers(self):
        class SlowHeaders(BaseHTTPRequestHandler):
            def do_GET(self):
                try:
                    for byte in b'HTTP/1.1 200 OK\r\nContent-Length: 1\r\n\r\nx':
                        self.connection.sendall(bytes([byte]));time.sleep(.04)
                except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),SlowHeaders)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with patch('desktop_rank.BASE',f'http://127.0.0.1:{server.server_port}'),patch('desktop_rank.TOTAL_SECONDS',.2):
                started=time.monotonic()
                with self.assertRaisesRegex(ValueError,'超时'):upstream_page('hot',1)
                self.assertLess(time.monotonic()-started,1)
        finally:server.shutdown();server.server_close();thread.join(2)

    def test_deadline_does_not_join_stalled_dns(self):
        import desktop_rank
        import httpx
        entered=threading.Event();release=threading.Event();original=socket.getaddrinfo
        def stalled(host,*args,**kwargs):
            if host in ('deadline.test',b'deadline.test'):
                entered.set();release.wait(2);host='127.0.0.1'
            return original(host,*args,**kwargs)
        factory=lambda **options:httpx.AsyncClient(verify=desktop_rank._SSL_CONTEXT,trust_env=False,**options)
        # Load HTTPX/AnyIO's lazy network backend before the tiny DNS budget.
        # Cold portable installs may otherwise time out before reaching DNS.
        with patch('desktop_rank.BASE','http://127.0.0.1:9'):
            with self.assertRaises(ValueError):upstream_page('hot',1,factory)
        try:
            with patch('socket.getaddrinfo',stalled),patch('desktop_rank.BASE','http://deadline.test:9'),patch('desktop_rank.TOTAL_SECONDS',.2):
                started=time.monotonic()
                with self.assertRaisesRegex(ValueError,'超时'):upstream_page('hot',1,factory)
                self.assertTrue(entered.is_set())
                self.assertLess(time.monotonic()-started,1)
        finally:release.set()

    def test_invalid_requests_make_no_network_call(self):
        service=DesktopRank(lambda *args:self.fail('Unexpected network'))
        for args in [('unknown',1),('hot',0),('hot',6),('hot',True),('hot',1,'true')]:
            with self.assertRaises(ValueError):service.page(*args)

    def test_upstream_wire_one_rank_request_and_bounded_body(self):
        calls=[];options=[]
        class Reply:
            status_code=200
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            def raise_for_status(self):pass
            async def aiter_bytes(self,size):yield payload().encode()
        class Client:
            def __init__(self,**kwargs):options.append(kwargs)
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def aclose(self):pass
            def stream(self,*args,**kwargs):calls.append((args,kwargs));return Reply()
        upstream_page('hot',2,Client)
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][0],('GET','https://hongguoduanju.com/rank/hot-drama'))
        self.assertEqual(calls[0][1]['params']['page'],2)
        self.assertEqual(calls[0][1]['params']['__loader'],'rank_hot-drama/page')
        self.assertFalse(options[0]['follow_redirects'])
        with patch('desktop_rank.MAX_BYTES',1):
            with self.assertRaises(ValueError):upstream_page('hot',1,Client)

    def test_local_route_origin_and_header(self):
        calls=[];service=DesktopRank(lambda board,page:(calls.append(1) or payload()))
        endpoint=make_router(service).routes[0].endpoint
        def request(headers):return Request({'type':'http','client':('127.0.0.1',1234),'headers':[(k.encode(),v.encode()) for k,v in headers.items()]})
        good={'origin':'http://tauri.localhost','x-desktop-rank-client':'1'}
        self.assertEqual(endpoint(request(good),'hot',1,False)[0]['episodeCount'],162)
        for headers,board,code in [({'origin':'http://tauri.localhost'},'hot',401),
                                  ({**good,'origin':'https://evil.test'},'hot',403),
                                  (good,'invalid',502)]:
            with self.assertRaises(HTTPException) as raised:endpoint(request(headers),board,1,False)
            self.assertEqual(raised.exception.status_code,code)
        self.assertEqual(len(calls),1)

    def test_transport_reuses_client_and_loop_and_closes_with_router(self):
        import asyncio
        loops=[];created=[];closed=[]
        class Reply:
            status_code=200
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            def raise_for_status(self):pass
            async def aiter_bytes(self,size):yield payload().encode()
        class Client:
            def __init__(self,**kwargs):created.append(1)
            async def aclose(self):closed.append(1)
            def stream(self,*args,**kwargs):
                loops.append(asyncio.get_running_loop());return Reply()
        service=DesktopRank(client_factory=Client)
        router=make_router(service)
        async def run():
            async with router.lifespan_context(None):
                self.assertEqual(service.page('hot',1)[0]['episodeCount'],162)
                self.assertEqual(service.page('hot',1,True)[0]['episodeCount'],162)
        try:asyncio.run(run())
        finally:service.close()
        self.assertEqual(len(created),1)
        self.assertEqual(loops,[loops[0],loops[0]])
        self.assertEqual(closed,[1])
        self.assertFalse(service.transport.thread.is_alive())
        self.assertTrue(service.transport.loop.is_closed())
        with self.assertRaisesRegex(ValueError,'已关闭'):service.page('hot',1,True)


if __name__=='__main__':unittest.main()
