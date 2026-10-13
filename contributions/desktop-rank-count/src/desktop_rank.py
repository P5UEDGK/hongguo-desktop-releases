"""Read complete official rank loader data with one upstream request per page."""
import asyncio
import json
import re
import threading
import time
from concurrent.futures import Future, TimeoutError as FutureTimeout
from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter, HTTPException, Request

BASE = 'https://hongguoduanju.com'
BOARDS = {'hot': 'hot-drama', 'real': 'hot-real-drama',
          'comic': 'hot-comic-drama', 'ai': 'hot-ai-drama'}
ORIGINS = ('http://tauri.localhost', 'tauri://localhost')
ID = re.compile(r'[0-9]{8,24}').fullmatch
MAX_BYTES = 8 * 1024 * 1024
TOTAL_SECONDS = 20.0
# Reuse verified trust roots instead of rebuilding them in each timed request.
_SSL_CONTEXT = httpx.create_ssl_context()


def _client_factory(**options):
    return httpx.AsyncClient(verify=_SSL_CONTEXT, **options)


class RankTransport:
    """One service-owned loop/client; a timed request never joins DNS workers."""
    def __init__(self, client_factory=None):
        self.factory = client_factory or _client_factory
        self.lock = threading.Lock()
        self.loop = self.thread = self.client = None
        self.closed = False

    def page(self, board, page):
        with self.lock:
            if self.closed:
                raise ValueError('排行榜服务已关闭')
            if self.loop is None:
                self.loop = asyncio.new_event_loop()
                self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
                self.thread.start()
            future = asyncio.run_coroutine_threadsafe(self._load(board, page), self.loop)
        try:
            return future.result(timeout=TOTAL_SECONDS)
        except (FutureTimeout, httpx.TimeoutException) as error:
            future.cancel()
            raise ValueError('排行榜请求超时，请重试') from error
        except (httpx.HTTPError, OSError, UnicodeError) as error:
            raise ValueError('排行榜暂时无法连接，请重试') from error

    async def _load(self, board, page):
        if self.client is None:
            self.client = self.factory(timeout=httpx.Timeout(15, connect=5), follow_redirects=False)
        return await _upstream_page(board, page, self.client)

    async def _close(self):
        tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.client is not None:
            await self.client.aclose()

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            loop, thread = self.loop, self.thread
        if loop is not None:
            future = asyncio.run_coroutine_threadsafe(self._close(), loop)
            try:
                future.result(timeout=2)
            except (FutureTimeout, httpx.HTTPError, OSError):
                future.cancel()
            finally:
                loop.call_soon_threadsafe(loop.stop)
                thread.join(timeout=2)
                if not thread.is_alive():
                    # close() does not join asyncio's resolver executor.
                    loop.close()


async def _upstream_page(board, page, client):
    route = BOARDS[board]
    params = {'__loader': 'rank_' + route + '/page', '__ssrDirect': 'true'}
    if page != 1:
        params['page'] = page
    async with client.stream('GET', BASE + '/rank/' + route, params=params) as response:
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError('排行榜响应异常，请重试')
        chunks, size = [], 0
        async for chunk in response.aiter_bytes(65536):
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError('排行榜响应过大，请重试')
            chunks.append(chunk)
        return b''.join(chunks).decode('utf-8')


def parse_page(text, page):
    """Modern.js sends metadata, then data: frames resolving deferred content."""
    try:
        frames = text.replace('\r\n', '\n').strip().split('\n\n')
        payload = json.loads(frames[0])
        if not isinstance(payload, dict):
            raise ValueError()
        pending = payload.get('content') == '__deferred_promise:content'
        resolved = False
        for frame in frames[1:]:
            if frame.startswith('error:'):
                raise ValueError()
            if not frame.startswith('data:'):
                raise ValueError()
            data = json.loads(frame[5:])
            if not isinstance(data, dict):
                raise ValueError()
            if 'content' in data:
                if not pending or resolved:
                    raise ValueError()
                payload['content'] = data['content']
                resolved = True
        content = payload.get('content')
        if (payload.get('pageNum') != page or not isinstance(content, dict)
                or content.get('isSuccess') is not True):
            raise ValueError()
        rows = content.get('rankList')
        pagination = content.get('pagination')
        if (not isinstance(rows, list) or not rows or len(rows) > 100
                or not isinstance(pagination, dict) or pagination.get('pageNum') != page):
            raise ValueError()
        result, seen = [], set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError()
            sid, title, vids = row.get('seriesId'), row.get('title'), row.get('episodeVids')
            if (not isinstance(sid, str) or not ID(sid) or sid in seen
                    or not isinstance(title, str) or not title.strip()
                    or not isinstance(vids, list) or not 1 <= len(vids) <= 100000
                    or any(not isinstance(vid, str) or not ID(vid) for vid in vids)
                    or len(set(vids)) != len(vids)):
                raise ValueError()
            seen.add(sid)
            tags = row.get('tags')
            result.append({'seriesId': sid, 'title': title.strip(),
                           'cover': row.get('cover') if isinstance(row.get('cover'), str) else '',
                           'intro': row.get('description') if isinstance(row.get('description'), str) else '',
                           'actors': [], 'tags': [t for t in tags if isinstance(t, str)] if isinstance(tags, list) else [],
                           'episodeCount': len(vids), 'webAccessibleEpisodes': min(3, len(vids)),
                           'hotText': row.get('heatText') if isinstance(row.get('heatText'), str) else ''})
        return result
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        raise ValueError('排行榜数据不完整，请重试') from error


class DesktopRank:
    def __init__(self, request=None, clock=time.monotonic, ttl=1800, client_factory=None):
        self.transport = RankTransport(client_factory) if request is None else None
        self.request = self.transport.page if self.transport is not None else request
        self.clock, self.ttl = clock, ttl
        self.cache = {}
        self.lock = threading.Lock()
        self.inflight = {}

    def page(self, board, page, refresh=False):
        if not isinstance(board, str) or board not in BOARDS or type(page) is not int or not 1 <= page <= 5 or type(refresh) is not bool:
            raise ValueError('排行榜类型或页码无效')
        key = (board, page)
        with self.lock:
            cached = self.cache.get(key)
            if not refresh and cached is not None and cached[0] > self.clock():
                return cached[1]
            future = self.inflight.get(key)
            owner = future is None
            if owner:
                future = Future()
                self.inflight[key] = future
        if not owner:
            return future.result()
        try:
            result = parse_page(self.request(board, page), page)
        except BaseException as error:
            with self.lock:
                self.inflight.pop(key)
                future.set_exception(error)
            raise
        with self.lock:
            self.cache[key] = (self.clock() + self.ttl, result)
            self.inflight.pop(key)
            future.set_result(result)
        return result

    def close(self):
        if self.transport is not None:
            self.transport.close()


def make_router(service):
    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            await asyncio.to_thread(service.close)

    router = APIRouter(prefix='/desktop/rank', lifespan=lifespan)

    @router.get('')
    def rank(request: Request, board: str = 'hot', page: int = 1, refresh: bool = False):
        if (request.client is None or request.client.host not in ('127.0.0.1', '::1')
                or request.headers.get('origin') not in ORIGINS):
            raise HTTPException(403, '不允许的排行榜来源')
        if request.headers.get('x-desktop-rank-client') != '1':
            raise HTTPException(401, '需要桌面排行榜上下文')
        try:
            return service.page(board, page, refresh)
        except ValueError as error:
            raise HTTPException(502, str(error)) from None

    return router
