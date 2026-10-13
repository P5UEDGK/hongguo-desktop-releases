"""Read complete official rank loader data with one upstream request per page."""
import json
import re
import threading
import time
from concurrent.futures import Future

import requests
from fastapi import APIRouter, HTTPException, Request

BASE = 'https://hongguoduanju.com'
BOARDS = {'hot': 'hot-drama', 'real': 'hot-real-drama',
          'comic': 'hot-comic-drama', 'ai': 'hot-ai-drama'}
ORIGINS = ('http://tauri.localhost', 'tauri://localhost')
ID = re.compile(r'[0-9]{8,24}').fullmatch
MAX_BYTES = 8 * 1024 * 1024
TOTAL_SECONDS = 20.0


def upstream_page(board, page, request=requests.request):
    deadline = time.monotonic() + TOTAL_SECONDS
    route = BOARDS[board]
    params = {'__loader': 'rank_' + route + '/page', '__ssrDirect': 'true'}
    if page != 1:
        params['page'] = page
    try:
        with request('GET', BASE + '/rank/' + route,
                     params=params,
                     timeout=(5, 15), stream=True, allow_redirects=False) as response:
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError('排行榜响应异常，请重试')
            return _read_body(response, deadline)
    except (requests.RequestException, OSError, UnicodeError) as error:
        raise ValueError('排行榜暂时无法连接，请重试') from error


def _read_body(response, deadline):
    # Requests buffers iter_content chunks. A monotonic check only inside the
    # loop cannot stop a peer trickling bytes before a complete chunk arrives.
    shutdown = getattr(getattr(response, 'raw', None), 'shutdown', None)
    if not callable(shutdown):
        raise ValueError('排行榜连接不支持限时中断')
    expired, guard, finished = threading.Event(), threading.Lock(), False

    def expire():
        with guard:
            if not finished:
                expired.set()
                try:
                    shutdown()
                except (OSError, ValueError, RuntimeError):
                    pass  # The connection may already have finished reading.

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ValueError('排行榜请求超时，请重试')
    timer = threading.Timer(remaining, expire)
    timer.daemon = True
    timer.start()
    try:
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            if expired.is_set() or time.monotonic() >= deadline:
                raise ValueError('排行榜请求超时，请重试')
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError('排行榜响应过大，请重试')
            chunks.append(chunk)
        if expired.is_set() or time.monotonic() >= deadline:
            raise ValueError('排行榜请求超时，请重试')
        return b''.join(chunks).decode('utf-8')
    except (requests.RequestException, OSError) as error:
        if expired.is_set():
            raise ValueError('排行榜请求超时，请重试') from error
        raise
    finally:
        # Finish cancellation before __exit__ can release a reusable connection.
        with guard:
            finished = True
        timer.cancel()


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
    def __init__(self, request=upstream_page, clock=time.monotonic, ttl=1800):
        self.request, self.clock, self.ttl = request, clock, ttl
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


def make_router(service):
    router = APIRouter(prefix='/desktop/rank')

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
