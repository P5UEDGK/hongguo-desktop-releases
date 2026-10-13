"""Run the host's actual authentication middleware without loading its providers."""
import ast
import asyncio
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SERVER = Path(sys.argv.pop(1)) if len(sys.argv) > 1 else None


class Response:
    def __init__(self, body=None, status_code=200):
        self.body, self.status_code = body, status_code


class RateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        if SERVER is None:
            self.skipTest('Pass the integrated host server.py path')
        tree = ast.parse(SERVER.read_text(encoding='utf8'))
        function = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'auth_mw')
        function.decorator_list = []
        self.key, self.other = 'b' * 64, 'c' * 64
        self.namespace = dict(os=os, time=time, threading=threading,
            Request=object, JSONResponse=Response, _EXEMPT=('/',), _ADMIN_PREFIX='/admin',
            RATE_PER_MIN=120, _rl={}, _rl_lock=threading.Lock(),
            _keys=SimpleNamespace(is_valid=lambda key: key in (self.key, self.other)),
            _stats=dict(auth_fail=0, requests=0, errors=0))
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(SERVER), 'exec'), self.namespace)
        self.env = patch.dict(os.environ, {'HONGGUO_SESSION_API_KEY': self.key})
        self.env.start(); self.addCleanup(self.env.stop)

    async def send(self, path, key=None, host='127.0.0.1', method='GET'):
        request = SimpleNamespace(url=SimpleNamespace(path=path),
            headers={'x-api-key': self.key if key is None else key}, query_params={},
            client=SimpleNamespace(host=host) if host is not None else None, method=method)
        async def next_handler(_):
            return Response(status_code=204 if method == 'DELETE' else 200)
        return await self.namespace['auth_mw'](request, next_handler)

    async def test_owned_control_status_and_release_survive_long_playback(self):
        for index in range(1200):
            path = '/desktop/hls/' + 'a' * 32 + ('/status' if index % 2 else '/control')
            self.assertEqual((await self.send(path)).status_code, 200, index)
        self.assertEqual((await self.send('/desktop/hls/' + 'a' * 32, method='DELETE')).status_code, 204)
        self.assertEqual((await self.send('/desktop/hls', method='POST')).status_code, 200)

    async def test_release_survives_an_already_full_generic_bucket(self):
        self.namespace['_rl'][(self.key, True)] = [time.time()] * 600
        self.assertEqual((await self.send('/desktop/hls/'+'a'*32, method='DELETE')).status_code, 204)

    async def test_invalid_key_still_rejected(self):
        self.assertEqual((await self.send('/desktop/hls/capabilities', key='invalid')).status_code, 401)

    async def test_other_api_keys_keep_media_limit(self):
        for _ in range(600):
            self.assertEqual((await self.send('/desktop/hls/capabilities', key=self.other)).status_code, 200)
        self.assertEqual((await self.send('/desktop/hls/capabilities', key=self.other)).status_code, 429)

    async def test_non_loopback_and_unknown_clients_keep_media_limit(self):
        for host in ('192.0.2.1', None):
            self.namespace['_rl'].clear()
            for _ in range(600):
                self.assertEqual((await self.send('/desktop/hls/capabilities', host=host)).status_code, 200)
            self.assertEqual((await self.send('/desktop/hls/capabilities', host=host)).status_code, 429)

    async def test_general_api_and_similar_prefix_keep_normal_limit(self):
        for path in ('/rank', '/desktop/hlsx'):
            self.namespace['_rl'].clear()
            for _ in range(120):
                self.assertEqual((await self.send(path, key=self.other)).status_code, 200)
            self.assertEqual((await self.send(path, key=self.other)).status_code, 429)

    async def test_owned_catalog_series_switches_and_ipv6_have_no_allowance(self):
        for host in ('127.0.0.1', '::1'):
            for index in range(1200):
                path = ('/rank', '/detail', '/desktop/playback', '/desktop/hlsx')[index % 4]
                self.assertEqual((await self.send(path, host=host)).status_code, 200, index)
        self.assertEqual(self.namespace['_rl'], {})

    async def test_remote_catalog_still_has_normal_limit(self):
        for _ in range(120):
            self.assertEqual((await self.send('/detail', host='192.0.2.1')).status_code, 200)
        self.assertEqual((await self.send('/detail', host='192.0.2.1')).status_code, 429)

    async def test_unmanaged_mode_keeps_media_limit(self):
        with patch.dict(os.environ, {'HONGGUO_SESSION_API_KEY': ''}):
            for _ in range(600):
                self.assertEqual((await self.send('/desktop/hls/capabilities')).status_code, 200)
            self.assertEqual((await self.send('/desktop/hls/capabilities')).status_code, 429)


if __name__ == '__main__':
    unittest.main(verbosity=2)
