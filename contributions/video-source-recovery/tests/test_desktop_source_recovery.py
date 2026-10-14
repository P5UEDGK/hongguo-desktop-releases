"""Bounded mirror failover without mixing objects or leaking signed URLs."""
import unittest
import requests
from desktop_stream import ProgressiveSource, SourceReadError


class Response:
    def __init__(self, data, start, end, *, status=206, etag='"same"', total=None):
        self.status_code=status
        self.headers={'Content-Range':f'bytes {start}-{min(end,len(data)-1)}/{total or len(data)}'}
        if etag:self.headers['ETag']=etag
        self.data=data[start:min(end+1,len(data))];self.closed=False
    def iter_content(self,size):yield self.data
    def close(self):self.closed=True


class RecoveryTests(unittest.TestCase):
    def source(self, handler):
        self.calls=[];self.responses=[];self.data=b'a'*65536+b'b'*65536
        def request(method,url,**kw):
            start,end=map(int,kw['headers']['Range'][6:].split('-'))
            self.calls.append((url,start,dict(kw['headers'])))
            r=handler(url,start,end)
            self.responses.append(r);return r
        return ProgressiveSource('https://main.invalid/x?secret=main',request=request,identity='same',
            size=len(self.data),backup_urls=['https://backup.invalid/x?secret=backup'])

    def test_first_request_main_unavailable_backup_reads(self):
        s=self.source(lambda u,a,b:Response(self.data,a,b,status=503 if 'main.' in u else 206))
        self.assertEqual(s.block(0,lambda:False),self.data[:65536])
        self.assertEqual(len(self.calls),2);self.assertTrue(all(r.closed for r in self.responses))
        self.assertFalse(s.network_failed.is_set())
        self.assertNotIn('secret',repr(s));self.assertNotIn('secret',str(s.cache_identity()))

    def test_midstream_backup_requires_matching_strong_etag_and_length(self):
        for etag,total,okay in [('"same"',None,True),('"other"',None,False),(None,None,False),('"same"',999,False)]:
            with self.subTest(etag=etag,total=total):
                def handler(u,a,b):
                    if 'main.' in u:
                        if a:raise requests.ConnectionError('secret-main')
                        return Response(self.data,a,b)
                    return Response(self.data,a,b,etag=etag,total=total)
                s=self.source(handler);s.block(0,lambda:False)
                if okay:self.assertEqual(s.block(1,lambda:False),self.data[65536:])
                else:
                    with self.assertRaises(SourceReadError):s.block(1,lambda:False)
                    self.assertEqual(s.received,65536)
                self.assertNotIn('If-Range',self.calls[-1][2])

    def test_no_validator_does_not_mix_after_first_block(self):
        def handler(u,a,b):
            if 'main.' in u and a:raise requests.Timeout()
            return Response(self.data,a,b,etag=None)
        s=self.source(handler);s.block(0,lambda:False)
        with self.assertRaises(SourceReadError):s.block(1,lambda:False)

    def test_backup_without_etag_can_continue_if_primary_never_delivered_bytes(self):
        s=self.source(lambda u,a,b:Response(self.data,a,b,etag=None,
                        status=503 if 'main.' in u else 206))
        self.assertEqual(s.block(0,lambda:False),self.data[:65536])
        self.assertEqual(s.block(1,lambda:False),self.data[65536:])

    def test_429_and_invalid_ranges_do_not_switch(self):
        for status in [429,200]:
            s=self.source(lambda u,a,b:Response(self.data,a,b,status=status))
            with self.assertRaises(SourceReadError):s.block(0,lambda:False)
            self.assertEqual(len(self.calls),1)

    def test_cancel_never_switches_and_all_failures_are_bounded(self):
        s=self.source(lambda u,a,b:Response(self.data,a,b,status=503))
        with self.assertRaises(InterruptedError):s.block(0,lambda:True)
        self.assertFalse(self.calls)
        with self.assertRaises(SourceReadError):s.block(0,lambda:False)
        self.assertEqual(len(self.calls),2)
        self.assertTrue(all(r.closed for r in self.responses))

    def test_transport_retries_stop_and_invalid_urls_rejected(self):
        def handler(u,a,b):raise requests.Timeout('secret-url')
        s=self.source(handler)
        with self.assertRaises(SourceReadError) as error:s.block(0,lambda:False)
        self.assertEqual(len(self.calls),4)
        self.assertNotIn('secret',str(error.exception))
        with self.assertRaises(ValueError):
            ProgressiveSource('https://main.invalid/x',request=lambda:None,identity='x',
                              backup_urls=['https://user:password@backup.invalid/x'])


if __name__=='__main__':unittest.main()
