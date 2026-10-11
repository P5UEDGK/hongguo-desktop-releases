// Host supplies React, JSX runtime and its existing authenticated endpoint resolver.
export function createComments({React: O, jsxRuntime: b, resolveEndpoint,
  installStyles, danmaku, emojis}) {
if (!resolveEndpoint || !installStyles || !danmaku || !emojis) throw Error('Missing social integration dependency');
const desktopDanmakuSettings = value => danmaku.settings(value);
const DesktopDanmakuSettings = props => b.jsx(danmaku.Settings, props);
const desktopStartDanmaku = (...args) => danmaku.start(...args);
const desktopLoadEmojis = endpoint => emojis.load(endpoint);
const DesktopEmojiText = props => b.jsx(emojis.Text, props);
function desktopSocialEndpoint(session) {
  try {
    const endpoint = resolveEndpoint(session.streamUrl);
    const params = new URL(endpoint.url).searchParams;
    const series = params.get('series_id'), episode = params.get('ep');
    if (!series || !episode) return null;
    return {...endpoint, series, episode};
  } catch {return null;}
}

async function desktopSocialRead(endpoint, resource, params = {}, signal, budget = 15000) {
  const url = new URL(endpoint.origin + '/desktop/social/' + resource);
  url.search = new URLSearchParams({series_id: endpoint.series, ep: endpoint.episode, ...params});
  const abort = new AbortController(), cancel = () => abort.abort();
  if (signal?.aborted) abort.abort();
  signal?.addEventListener('abort', cancel, {once:true});
  const timer = setTimeout(cancel, Math.max(0,budget));
  try {
    const response = await fetch(url, {headers: {'x-api-key': endpoint.key}, signal:abort.signal,
      credentials: 'omit', redirect: 'error', cache: 'no-store'});
    if (!response.ok) throw Error('加载失败，请重试');
    return await response.json();
  } finally {clearTimeout(timer); signal?.removeEventListener('abort', cancel);}
}

// One store per episode session. Visibility controls subscribers, not the request.
function desktopSocialStore(endpoint) {
  const entries = new Map();
  const identity = (resource, params) => JSON.stringify([resource, params.kind || params.comment_id || '']);
  function clear(resource, params) {
    for (const [key, entry] of entries) if ((!resource || entry.resource === resource)
      && (!params || key === identity(resource, params))) {entry.abort.abort(); entries.delete(key);}
  }
  function read(resource, params = {}, deadline = Date.now()+15000) {
    if (Date.now() >= deadline) return Promise.reject(new DOMException("Read deadline expired", "TimeoutError"));
    const key = identity(resource, params), cursor = params.cursor || '';
    let entry = entries.get(key);
    if (!entry) {
      if (entries.size >= 32) {const oldest = entries.keys().next().value; entries.get(oldest).abort.abort(); entries.delete(oldest);}
      entry = {resource, abort:new AbortController(), value:null, pending:null, cursors:new Set()}; entries.set(key, entry);
    }
    if (entry.value && entry.cursors.has(cursor)) return Promise.resolve(entry.value);
    if (entry.pending) {
      if (entry.pendingCursor === cursor) return entry.pending;
      let timer;
      return Promise.race([
        entry.pending.catch(() => {}).then(() => {
          if (entry.abort.signal.aborted) throw new DOMException('Aborted', 'AbortError');
          return read(resource, params, deadline);
        }),
        new Promise((_,reject)=>{timer=setTimeout(()=>reject(new DOMException('Read deadline expired','TimeoutError')),Math.max(0,deadline-Date.now()));})
      ]).finally(()=>clearTimeout(timer));
    }
    entry.pendingCursor = cursor;
    if (entry.abort.signal.aborted) entry.abort = new AbortController();
    const timer = setTimeout(() => entry.abort.abort(), Math.max(0,deadline-Date.now()));
    entry.pending = desktopSocialRead(endpoint, resource, params, entry.abort.signal, deadline-Date.now()).then(result => {
      if (entry.abort.signal.aborted || entries.get(key) !== entry) throw new DOMException('Aborted', 'AbortError');
      const page = resource === 'comments' || resource === 'replies';
      if (page && !cursor) entry.cursors.clear();
      entry.value = page ? {...result, has_more:result.has_more && result.cursor !== cursor,
        items:cursor && entry.value ? [...new Map([...entry.value.items, ...result.items].map(item => [item.id,item])).values()] : result.items} : result;
      entry.cursors.add(cursor); return entry.value;
    }).catch(error => {
      if (!entry.value && entries.get(key) === entry) entries.delete(key);
      throw error;
    }).finally(() => {clearTimeout(timer); entry.pending = null;});
    return entry.pending;
  }
  return {read, clear, dispose:() => clear()};
}

function desktopSocialPreference(name, fallback) {
  try {const value = localStorage.getItem('hongguo:' + name); return value === null ? fallback : value === 'on';}
  catch {return fallback;}
}

function desktopSocialSet(media, changes) {
  if (!media) return;
  for (const name of ['danmaku', 'social']) if (typeof changes[name] === 'boolean') {
    try {localStorage.setItem('hongguo:' + name, changes[name] ? 'on' : 'off');} catch {}
  }
  if (changes.settings) {
    changes.settings = desktopDanmakuSettings(changes.settings);
    try {localStorage.setItem('hongguo:danmakuSettings', JSON.stringify(changes.settings));} catch {}
    try {localStorage.setItem('hongguo:danmakuSettingsVersion','2');} catch {}
  }
  media.dispatchEvent(new CustomEvent('desktopsocialsettings', {detail: changes}));
}

function DesktopSocialControls({media, sessionKey}) {
  const [social, setSocial] = O.useState(false), [danmakuError,setDanmakuError] = O.useState('');
  O.useEffect(()=>{
    const video=media.current, changed=event=>setDanmakuError(event.detail || '');
    setDanmakuError(video?.desktopDanmakuStatus || '');
    video?.addEventListener('desktopdanmakustatus',changed);
    return ()=>video?.removeEventListener('desktopdanmakustatus',changed);
  },[sessionKey]);
  O.useEffect(() => {
    const video = media.current; setSocial(false);
    const changed = event => {
      if (typeof event.detail.comments === 'boolean') setSocial(event.detail.comments);
      if (event.detail.social === false) setSocial(false);
    };
    video?.addEventListener('desktopsocialsettings', changed);
    return () => video?.removeEventListener('desktopsocialsettings', changed);
  }, [sessionKey]);
  return b.jsxs('span', {className: 'desktop-social-controls', children: [
    b.jsx(DesktopDanmakuSettings,{media,sessionKey}),
    danmakuError && b.jsx('span',{className:'desktop-social-error',role:'status',title:danmakuError,children:'弹幕加载失败'}),
    b.jsx('button', {className: 'desktop-social-toggle', 'aria-label': '评论与互动', 'aria-pressed': social,
      'aria-controls': 'desktop-social-drawer', title: '评论、点赞数和收藏数',
      onClick: async () => {
        if (!social && document.fullscreenElement) try {await document.exitFullscreen();} catch {}
        desktopSocialSet(media.current, {social: true, comments: !social, tab: social ? 'episodes' : 'episode'});
      }, children: '评论'}),
  ]});
}

function SocialSession({session, media}) {
  const endpoint = desktopSocialEndpoint(session), key = session.streamUrl;
  const [store] = O.useState(() => desktopSocialStore(endpoint));
  O.useEffect(() => () => store.dispose(), [store]);
  const [stats, setStats] = O.useState(null), [statsError, setStatsError] = O.useState('');
  const [tab, setTab] = O.useState('episodes'), [page, setPage] = O.useState(null);
  const [error, setError] = O.useState(''), [busy, setBusy] = O.useState(false);
  const [refresh, setRefresh] = O.useState(0), [metricsRefresh, setMetricsRefresh] = O.useState(0);
  const consumedMetricsRefresh = O.useRef(0);
  const consumedCommentsRefresh = O.useRef(0);
  const [danmaku, setDanmaku] = O.useState(() => desktopSocialPreference('danmaku', true));
  const [drawer, setDrawer] = O.useState(() => desktopSocialPreference('social', false));
  const [comments, setComments] = O.useState(false);
  const commenting = drawer && comments && tab !== 'episodes';
  const current = O.useRef(null);
  const [,refreshEmojis]=O.useState(0);
  O.useEffect(()=>{
    const changed=()=>refreshEmojis(value=>value+1);
    window.addEventListener('desktopemojis',changed);
    if(endpoint)desktopLoadEmojis(endpoint);
    return ()=>window.removeEventListener('desktopemojis',changed);
  },[key]);
  O.useEffect(() => {installStyles();}, []);
  O.useEffect(() => {
    const video = media.current;
    const changed = event => {
      if (typeof event.detail.danmaku === 'boolean') setDanmaku(event.detail.danmaku);
      if (typeof event.detail.social === 'boolean') setDrawer(event.detail.social);
      if (typeof event.detail.comments === 'boolean') setComments(event.detail.comments);
      if (event.detail.social === false || event.detail.comments === false) {setComments(false); setTab('episodes'); return;}
      if (['episode', 'series', 'episodes'].includes(event.detail.tab)) setTab(event.detail.tab);
    };
    video?.addEventListener('desktopsocialsettings', changed);
    return () => video?.removeEventListener('desktopsocialsettings', changed);
  }, [key]);
  O.useEffect(() => {
    const video = media.current, layout = video?.closest('.desktop-player-layout');
    layout?.classList.toggle('desktop-social-enabled', drawer);
    layout?.querySelector('aside')?.setAttribute('aria-label', '选集与评论抽屉');
    const frame = requestAnimationFrame(() => video?.dispatchEvent(new Event('desktopsociallayout')));
    return () => {cancelAnimationFrame(frame); layout?.classList.remove('desktop-social-enabled');};
  }, [key, drawer]);
  O.useEffect(() => {
    const abort = new AbortController(); setStats(null); setStatsError('');
    const forceRefresh = metricsRefresh !== consumedMetricsRefresh.current;
    consumedMetricsRefresh.current = metricsRefresh;
    if (forceRefresh) store.clear('metrics');
    if (endpoint && commenting) store.read('metrics', {refresh: forceRefresh})
      .then(value => {if (!abort.signal.aborted) setStats(value);})
      .catch(e => {if (!abort.signal.aborted) setStatsError('互动计数加载失败，请重试');});
    return () => abort.abort();
  }, [key, metricsRefresh, commenting]);
  O.useEffect(() => {
    const own = {abort: new AbortController(), busy: false}; current.current = own;
    setPage(null); setError('');
    setBusy(false);
    if (refresh !== consumedCommentsRefresh.current) {store.clear('comments', {kind:tab}); if (tab === 'episode') store.clear('replies');}
    consumedCommentsRefresh.current = refresh;
    if (endpoint && commenting) load('', own);
    return () => {own.abort.abort(); if (current.current === own) current.current = null;};
  }, [key, tab, refresh, commenting]);
  async function load(cursor = '', own = current.current) {
    if (!own || own.busy || own.abort.signal.aborted) return;
    own.busy = true; setBusy(true); setError('');
    try {
      const result = await store.read('comments', {kind: tab, cursor});
      if (current.current !== own) return;
      setPage(previous => ({...result, has_more: result.has_more && result.cursor !== cursor,
        items: cursor && previous ? [...new Map([...previous.items, ...result.items].map(item => [item.id, item])).values()] : result.items}));
    } catch(e) {if (!own.abort.signal.aborted && current.current === own) setError('评论加载失败，请重试');}
    finally {own.busy = false; if (current.current === own) setBusy(false);}
  }
  O.useEffect(() => {
    const video=media.current;
    const status=message=>{if(video){video.desktopDanmakuStatus=message;video.dispatchEvent(new CustomEvent('desktopdanmakustatus',{detail:message}));}};
    status('');
    try {localStorage.setItem('hongguo:danmaku', danmaku ? 'on' : 'off');} catch {}
    if (!endpoint || !danmaku || !media.current) return;
    const stop=desktopStartDanmaku(video, endpoint, status);
    return ()=>{stop?.();status('');};
  }, [key, danmaku]);
  if (!endpoint) return null;
  return b.jsxs('section', {id: 'desktop-social-drawer', className: 'desktop-social', 'data-tab': tab,
    'aria-label': tab === 'episodes' ? '选集' : '评论与互动', hidden: !drawer, children: [
    b.jsxs('div', {className: 'desktop-social-navigation', children: [
    b.jsxs('div', {className: 'desktop-social-tabs', role: 'tablist', 'aria-label': '抽屉内容', children: [
      ...[['episodes', '选集'], ...(comments ? [['episode', '本集评论'], ['series', '整剧剧评']] : [])].map(([name, label]) => b.jsx('button', {
        role: 'tab', 'aria-selected': tab === name, onClick: () => desktopSocialSet(media.current, {social: true, tab: name}), children: label}, name))]}),
    b.jsx('button', {className: 'desktop-social-close', 'aria-label': tab === 'episodes' ? '关闭右侧抽屉' : '关闭评论页面',
      title: tab === 'episodes' ? '关闭右侧抽屉' : '关闭评论页面，返回选集',
      onClick: () => {
        const video = media.current, wasEpisodes = tab === 'episodes';
        desktopSocialSet(video, {social: !wasEpisodes, ...(wasEpisodes ? {comments:false} : {}), tab: 'episodes'});
        const player = video?.closest('.desktop-player');
        player?.querySelector(wasEpisodes ? '.desktop-selection-open' : '.desktop-social-tabs [role=tab]')?.focus();
      }, children: '×'})]}),
    tab !== 'episodes' && b.jsxs('div', {className: 'desktop-social-toolbar', children: [
      b.jsx('span', {children: '本集赞 ' + (stats ? stats.likes.toLocaleString('zh-CN') : '…')}),
      b.jsx('span', {children: '评论 ' + (stats ? stats.comments.toLocaleString('zh-CN') : '…')}),
      b.jsx('button', {onClick: () => setMetricsRefresh(n => n + 1), 'aria-label': '刷新互动计数', children: '刷新'}),
      b.jsx('small', {className: 'desktop-social-favorite', children: '整剧收藏 ' + (stats ? stats.favorites.toLocaleString('zh-CN') : '…')})]}),
    tab !== 'episodes' && statsError && b.jsx('p', {className: 'desktop-social-error', role: 'status', children: statsError}),
    tab !== 'episodes' && b.jsxs('div', {className: 'desktop-social-list', role: 'tabpanel', 'aria-label': tab === 'episode' ? '本集评论' : '整剧剧评', children: [
      b.jsxs('div', {className: 'desktop-social-list-heading', children: [
        b.jsx('small', {className: 'desktop-social-status', children: page ? '共 ' + page.total.toLocaleString('zh-CN') + ' 条' : '评论'}),
        b.jsx('button', {disabled: busy, onClick: () => setRefresh(n => n + 1), children: '刷新评论'})]}),
      page?.items.map(item => b.jsx(DesktopSocialComment, {item, endpoint, store, replies: tab === 'episode'}, key + tab + item.id)),
      page && !page.items.length && b.jsx('p', {className: 'desktop-social-status', children: '暂无评论'}),
      error && b.jsxs('p', {className: 'desktop-social-error', role: 'status', children: [error, ' ', b.jsx('button', {
        onClick: () => load(page?.cursor || ''), children: '重试'})]}),
      busy && b.jsx('p', {className: 'desktop-social-status', role: 'status', children: '正在加载…'}),
      page?.has_more && b.jsx('button', {disabled: busy, onClick: () => load(page.cursor), children: '加载更多评论'})]})]});
}

function DesktopSocialComment({item, endpoint, store, replies}) {
  const [open, setOpen] = O.useState(false), [page, setPage] = O.useState(null);
  const [busy, setBusy] = O.useState(false), [error, setError] = O.useState('');
  const own = O.useRef(null);
  O.useEffect(() => {
    own.current = {abort: new AbortController(), busy: false};
    return () => {own.current.abort.abort();};
  }, []);
  async function load(cursor = '') {
    const request = own.current;
    if (!request || request.busy || request.abort.signal.aborted) return;
    request.busy = true; setBusy(true); setError('');
    try {
      const params = {comment_id:item.id, cursor};
      const result = await (store ? store.read('replies', params) : desktopSocialRead(endpoint, 'replies', params, request.abort.signal));
      if (own.current === request && !request.abort.signal.aborted) setPage(previous => ({...result, has_more: result.has_more && result.cursor !== cursor,
        items: cursor && previous ? [...new Map([...previous.items, ...result.items].map(row => [row.id, row])).values()] : result.items}));
    } catch (e) {if (!request.abort.signal.aborted) setError('回复加载失败，请重试');}
    finally {request.busy = false; if (!request.abort.signal.aborted) setBusy(false);}
  }
  return b.jsxs('article', {className: 'desktop-social-item', children: [
    b.jsx('strong', {children: item.author}),
    b.jsx('p', {children: b.jsx(DesktopEmojiText,{text:item.text || (item.image_count ? '[图片评论]' : '[无文字评论]')})}),
    b.jsx('small', {children: (item.created_at ? new Date(item.created_at * 1000).toLocaleDateString('zh-CN') + ' · ' : '') + '赞 ' + item.likes}),
    replies && item.replies > 0 && b.jsx('button', {'aria-expanded': open, onClick: () => {
      setOpen(!open); if (open) {own.current?.abort.abort(); own.current = {abort:new AbortController(),busy:false}; setBusy(false);} else if (!page && !busy) load();}, children: open ? '收起回复' : '查看 ' + item.replies + ' 条回复'}),
    open && b.jsxs('div', {className: 'desktop-social-replies', children: [
      page?.items.map(row => b.jsx(DesktopSocialComment, {item: row, endpoint, store, replies: false}, row.id)),
      page && !page.items.length && b.jsx('p', {children: '暂无回复'}),
      busy && b.jsx('p', {role: 'status', children: '正在加载回复…'}),
      error && b.jsxs('p', {role: 'status', children: [error, ' ', b.jsx('button', {onClick: () => load(page?.cursor || ''), children: '重试'})]}),
      page?.has_more && b.jsx('button', {disabled: busy, onClick: () => load(page.cursor), children: '加载更多回复'})]})]});
}

function DesktopSocial(props) {return b.jsx(SocialSession, props, props.session.streamUrl);}
return {Drawer:DesktopSocial, Controls:DesktopSocialControls, Comment:DesktopSocialComment,
  read:desktopSocialRead, createStore:desktopSocialStore, preference:desktopSocialPreference, set:desktopSocialSet, endpoint:desktopSocialEndpoint};
}
