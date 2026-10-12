"""Novelfm desktop search. GET query parameters are the upstream wire contract."""
import json
import re
import secrets
import threading
import time
import requests

from fastapi import APIRouter, Depends, HTTPException, Request

ENDPOINT = 'https://api5-sinfonlinea.novelfm.com/novelfm/bookmall/search/page/v1/'
ORIGINS = ('http://tauri.localhost', 'tauri://localhost')
ID = re.compile(r'[0-9]{8,24}').fullmatch


def upstream_get(params, request=requests.request):
    # The upstream also emits transient business code 6000 with HTTP 200.
    # Retry this read once; a second failure remains an error, never an empty page.
    for attempt in range(2):
        try:
            payload = _upstream_get_once(params, request)
        except ValueError:
            if attempt:
                raise
        else:
            if not isinstance(payload, dict) or payload.get('code') != 6000 or attempt:
                return payload
        time.sleep(0.3)


def _upstream_get_once(params, request):
    try:
        with request('GET', ENDPOINT, params=params, timeout=(5, 8), stream=True) as response:
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 4 * 1024 * 1024:
                    raise ValueError('搜索响应过大，请重试')
                chunks.append(chunk)
            return json.loads(b''.join(chunks))
    except (requests.RequestException, OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('搜索服务暂时无法连接，请重试') from error


def records(value, depth=0):
    if depth > 8:
        raise ValueError('搜索结果嵌套过深')
    if isinstance(value, list):
        for child in value:
            yield from records(child, depth + 1)
    elif isinstance(value, dict):
        containers = [value[key] for key in ('books', 'items', 'search_data') if key in value]
        if containers:
            for child in containers:
                if not isinstance(child, list):
                    raise ValueError('搜索结果列表格式异常')
                yield from records(child, depth + 1)
        elif 'book_id' in value and 'book_name' in value:
            yield value
        else:
            raise ValueError('搜索记录缺少剧集信息')
    else:
        raise ValueError('搜索结果格式异常')


def summary(book):
    sid, title = book.get('book_id'), book.get('book_name')
    if type(sid) not in (str, int) or not ID(str(sid)) or not isinstance(title, str) or not title.strip():
        raise ValueError('搜索记录包含无效 ID 或剧名')
    count = book.get('chapter_number') or book.get('serial_count') or 0
    if type(count) not in (str, int) or not str(count).isdigit() or not 0 <= int(count) <= 100000:
        raise ValueError('搜索记录集数异常')
    tags = []
    try:
        categories = json.loads(book.get('category_info') or '[]')
        if isinstance(categories, list):
            tags = [row['Name'] for row in categories if isinstance(row, dict) and isinstance(row.get('Name'), str)]
    except (ValueError, TypeError):
        pass  # Categories are decorative; identity and pagination are mandatory.
    actors = book.get('actors') or ''
    actors = [part.strip() for part in re.split(r'[,，、/]', actors) if part.strip()] if isinstance(actors, str) else []
    cover = book.get('thumb_url') or book.get('thumb_pic') or book.get('audio_thumb_uri') or ''
    return {'seriesId': str(sid), 'title': title.strip(), 'source':'novelfm', 'cover': cover if isinstance(cover, str) else '',
            'intro': str(book.get('abstract') or ''), 'actors': actors, 'tags': tags,
            'episodeCount': int(count), 'webAccessibleEpisodes': 0,
            'hotText': str(book.get('stat_rank_desc') or '')}


class DesktopSearch:
    def __init__(self, request=upstream_get, clock=time.monotonic, ttl=600, capacity=64):
        self.request, self.clock, self.ttl, self.capacity = request, clock, ttl, capacity
        self.states = {}
        self.lock = threading.Lock()
        self.request_token = secrets.token_hex(32)

    def page(self, query, page, mode):
        if not isinstance(query, str) or not query.strip() or len(query) > 80:
            raise ValueError('请输入1至80个字的搜索词')
        if type(page) is not int or not 1 <= page <= 100 or mode not in ('short', 'manju'):
            raise ValueError('搜索页码或类型无效')
        query = query.strip()
        key = (query, mode)
        with self.lock:
            now = self.clock()
            self.states = {k: s for k, s in self.states.items() if s['expires'] > now}
            state = self.states.get(key) if page != 1 else None
            if page != 1:
                if state is None:
                    raise ValueError('搜索会话已过期，请重新搜索')
                if page in state['pages']:
                    return state['pages'][page]
                if page != len(state['pages']) + 1 or not state['more']:
                    raise ValueError('搜索游标无效，请重新搜索')
            offset, search_id = (state['offset'], state['search_id']) if state else (0, '')
            tab = 13 if mode == 'manju' else 10
            params = {'device_platform':'android', 'aid':'3040', 'manifest_version_code':'628',
                      'update_version_code':'62832', 'limit':20, 'offset':offset, 'query':query,
                      'search_ctx_info':'',
                      'search_entrance':json.dumps({'type':1, 'tab_type':39, 'default_tab_type':10,
                                                   'bottom_type':1, 'search_tab_id':tab}, separators=(',', ':')),
                      'sub_tab_type':31, 'tab_type':tab}
            if search_id:
                params['search_id'] = search_id
            payload = self.request(params)
            if not isinstance(payload, dict) or type(payload.get('code')) is not int or payload['code'] != 0:
                raise ValueError('搜索服务未返回成功状态，请重试')
            data = payload.get('data')
            if not isinstance(data, dict) or not isinstance(data.get('search_data'), list):
                raise ValueError('搜索响应缺少结果列表')
            more = data.get('has_more')
            if type(more) not in (bool, int) or more not in (False, True, 0, 1):
                raise ValueError('搜索响应缺少明确结束标记')
            if data.get('tab_type', tab) != tab:
                raise ValueError('搜索响应类型不匹配')
            rows = [summary(book) for book in records(data['search_data'])]
            if len(rows) > 20 or more and not rows:
                raise ValueError('搜索页大小异常或空页仍声明更多结果')
            seen = set(state['seen']) if state else set()
            for row in rows:
                if row['seriesId'] in seen:
                    raise ValueError('搜索结果跨页重复，请重新搜索；未判定为末页')
                seen.add(row['seriesId'])
            nxt, sid = data.get('next_offset'), data.get('search_id')
            if more:
                if type(nxt) is not int or nxt <= offset:
                    raise ValueError('搜索游标未推进，不能继续翻页')
                if not isinstance(sid, str) or not sid:
                    raise ValueError('搜索响应缺少会话标识')
            result = {'items':rows, 'page':page, 'hasMore':bool(more), 'mode':mode,
                      'source':'novelfm', 'coverage':'unverified', 'retrievedCount':len(seen)}
            if state is None:
                if key not in self.states and len(self.states) >= self.capacity:
                    self.states.pop(min(self.states, key=lambda k: self.states[k]['expires']))
                state = {'pages':{}}
                self.states[key] = state
            state.update(offset=nxt, search_id=sid, more=bool(more), seen=seen, expires=self.clock()+self.ttl)
            state['pages'][page] = result
            return result


def make_router(service):
    router = APIRouter(prefix='/desktop/search')

    def check(request: Request):
        if request.client is None or request.client.host not in ('127.0.0.1', '::1') or request.headers.get('origin') not in ORIGINS:
            raise HTTPException(403, '不允许的搜索来源')
        if request.headers.get('x-desktop-search-client') != '1':
            raise HTTPException(401, '需要桌面搜索上下文')
        if request.method != 'GET' and not secrets.compare_digest(request.headers.get('x-desktop-search-token', ''), service.request_token):
            raise HTTPException(401, '搜索会话已失效，请重试')

    @router.get('', dependencies=[Depends(check)])
    def access():
        return {'requestToken':service.request_token}

    @router.post('', dependencies=[Depends(check)])
    def search(value: dict):
        try:
            return service.page(value.get('query'), value.get('page'), value.get('mode'))
        except ValueError as error:
            raise HTTPException(502, str(error)) from None

    return router
