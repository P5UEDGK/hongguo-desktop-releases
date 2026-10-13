// Library membership is saved through the original Tauri commands only.
// This module owns relationship views and the shared search scheduler.
function desktopLibraryCancelled() { return new Error('搜索已取消'); }

class DesktopSearchQueue {
  constructor(notify = () => {}) {
    this.notify = notify; this.queue = []; this.active = null; this.tasks = new Map();
  }
  state() {
    return {label:this.active?.label || '', cancelled:!!this.active?.cancelled, waiting:this.queue.length};
  }
  run(key, label, work, {background = false} = {}) {
    if (this.tasks.has(key)) {
      const task=this.tasks.get(key);if(!background)task.background=false;
      return task.promise;
    }
    if (this.queue.length >= 64) return Promise.reject(Error('等待搜索过多，请稍后重试'));
    let resolve, reject;
    const promise = new Promise((a, b) => {resolve=a; reject=b;});
    const task = {key, label, work, promise, resolve, reject, background, cancelled:false, pending:new Set()};
    this.tasks.set(key, task); this.queue.push(task); this.pump(); this.notify();
    return promise;
  }
  async pump() {
    if (this.active || !this.queue.length) return;
    const index=this.queue.findIndex(task=>!task.background);
    const task = this.active = this.queue.splice(index<0?0:index,1)[0]; this.notify();
    await this.execute(task);
    this.active=null;this.notify();this.pump();
  }
  async execute(task) {
    const context = {
      live:() => !task.cancelled,
      request:async fn => {
        // Yield only between settled native requests. A timed-out IPC still
        // occupies the global slot until its original promise settles.
        if(task.background) {
          await Promise.allSettled([...task.pending]);
          let index;
          while(!task.cancelled&&(index=this.queue.findIndex(row=>!row.background))>=0) {
            const foreground=this.queue.splice(index,1)[0];this.active=foreground;this.notify();
            await this.execute(foreground);this.active=task;this.notify();
          }
        }
        if (task.cancelled) return Promise.reject(desktopLibraryCancelled());
        const request = Promise.resolve().then(fn);
        task.pending.add(request);
        request.then(() => task.pending.delete(request), () => task.pending.delete(request));
        return request;
      }
    };
    let value, error;
    try {value = await task.work(context); if (task.cancelled) throw desktopLibraryCancelled();}
    catch (caught) {error = caught;}
    // Promise.race in the old season finder cannot abort native IPC. Keep the
    // slot until that original request settles, even after timeout/cancellation.
    await Promise.allSettled([...task.pending]);
    if (task.cancelled && !error) error = desktopLibraryCancelled();
    this.tasks.delete(task.key);
    error ? task.reject(error) : task.resolve(value);
    this.notify();
  }
  cancel() {
    for(const task of this.tasks.values())task.cancelled=true;
    for (const task of this.queue.splice(0)) {
      this.tasks.delete(task.key); task.reject(desktopLibraryCancelled());
    }
    this.notify();
  }
}

function desktopLibraryGroups(items, relations, manual, sharedItems = items) {
  if (sharedItems !== items) {
    const shared = new Map(desktopLibraryGroups([...sharedItems,...items],relations,manual).map(group=>[group.key,group]));
    // Each root keeps its own series visibility; folders use one shared membership.
    return desktopLibraryGroups(items,relations,manual).map(group=>shared.get(group.key)||group);
  }
  const groups = new Map();
  for (const item of items) {
    const relation = relations.get(item.seriesId);
    const key = manual.get(item.seriesId) || (relation?.albumId ? 'album:' + relation.albumId : 'series:' + item.seriesId);
    if (!groups.has(key)) groups.set(key, []);
    const group = groups.get(key);
    if (!group.some(row => row.seriesId === item.seriesId)) group.push(item);
  }
  return [...groups].map(([key, rows]) => ({key, items:rows.sort((a,b) =>
    (relations.get(a.seriesId)?.season ?? 1000) - (relations.get(b.seriesId)?.season ?? 1000)
    || a.seriesId.localeCompare(b.seriesId))}));
}

function desktopLibrarySortSeasons(items, relations, order = 'desc') {
  const season = item => {
    const value=relations.get(item.seriesId)?.season;
    return Number.isSafeInteger(value)&&value>0?value:null;
  };
  return [...items].sort((a,b)=>{
    const left=season(a),right=season(b);
    if(left===null||right===null)return (left===null)-(right===null)||a.seriesId.localeCompare(b.seriesId);
    return (order==='asc'?left-right:right-left)||a.seriesId.localeCompare(b.seriesId);
  });
}

function desktopLibrarySortGroups(groups, records, order, titleOf, history = []) {
  const titles=new Intl.Collator('zh-CN',{numeric:true,sensitivity:'base'});
  const times=new Map(records.map(item=>[item.seriesId,Number.isFinite(Number(item.updatedAt))?Number(item.updatedAt):0]));
  const played=new Map(history.map(item=>[item.seriesId,Number.isFinite(Number(item.updatedAt))?Number(item.updatedAt):0]));
  const latest=group=>Math.max(0,...group.items.map(item=>times.get(item.seriesId)||0));
  const watched=group=>group.items.some(item=>played.has(item.seriesId));
  const lastPlayed=group=>Math.max(0,...group.items.map(item=>played.get(item.seriesId)||0));
  const compareTitle=(a,b)=>titles.compare(titleOf(a),titleOf(b));
  return [...groups].sort((a,b)=>{
    const primary=order==='played'?(watched(b)-watched(a)||lastPlayed(b)-lastPlayed(a)||latest(b)-latest(a)):
      order==='title-asc'?compareTitle(a,b):order==='title-desc'?compareTitle(b,a):latest(b)-latest(a);
    return primary||compareTitle(a,b)||a.key.localeCompare(b.key);
  });
}

function desktopLibraryPage(items, page, size) {
  const pages=Math.max(1,Math.ceil(items.length/size));
  const current=Math.min(pages,Math.max(1,Number.isFinite(page)?Math.floor(page):1));
  return {items:items.slice((current-1)*size,current*size),page:current,pages,total:items.length};
}

function desktopLibraryProgress(items, history, relations = new Map()) {
  const members=new Map(items.map(item=>[item.seriesId,item]));
  let latest=null,latestTime=-Infinity;
  // Native history is newest first; stable input order breaks equal/missing timestamps.
  for (const row of history) {
    if (!members.has(row.seriesId) || !Number.isFinite(row.lastEpisode) || row.lastEpisode<1) continue;
    const time=Number(row.updatedAt)||0;
    if (!latest || time>latestTime) {latest=row;latestTime=time;}
  }
  if (!latest) return {label:'未观看',title:'暂无观看历史',percent:null,seriesId:null};
  const item=members.get(latest.seriesId),episode=Math.floor(latest.lastEpisode);
  const total=Number(item.episodeCount)>0?Number(item.episodeCount):Number(latest.episodeCount);
  const percent=Number.isFinite(total)&&total>0?Math.min(100,Math.max(0,Math.floor(episode/total*100))):null;
  const season=relations.get(latest.seriesId)?.season;
  const prefix=items.length>1?(season?`第 ${season} 季 · `:'最近一季 · '):'';
  return {label:prefix+(percent===null?`看到第 ${episode} 集`:`已看 ${percent}%`),
    title:`最近观看《${item.title}》第 ${episode} 集${percent===null?'，总集数未知':` / 共 ${total} 集`}`,
    percent,seriesId:latest.seriesId};
}

function desktopLibraryNext(seed,items,relations) {
  const current=relations.get(seed.seriesId);
  if(!current?.albumId||!Number.isSafeInteger(current.season)||current.season<1)return {items:[],automatic:false,incomplete:false};
  const candidates=[...new Map(items.filter(item=>item.seriesId!==seed.seriesId&&
    relations.get(item.seriesId)?.albumId===current.albumId&&relations.get(item.seriesId)?.season===current.season+1)
    .map(item=>[item.seriesId,item])).values()];
  const ambiguous=[...relations].some(([sid,row])=>row.albumId===current.albumId&&row.season===current.season+1&&sid!==candidates[0]?.seriesId);
  return {items:candidates,automatic:candidates.length===1&&!ambiguous,incomplete:false};
}

function desktopCreateLibrary(api, notify, options = {}) {
  const relations = new Map(), manual = new Map(), known = new Map(), pending = new Map();
  const removed = new Map(), writes = new Map(), choices=new Map(); let revision = 0;
  const members={favorites:new Set(),history:new Set()};
  let access = null, loading = null, draining = false, error = '';
  const excluded = new Set(), autoRetry = new Map();
  const exclusionKey = 'guoban:library-auto-favorite-exclusions:v1';
  let storage=options.storage, autoWork=null, autoDirty=false, autoScheduled=false;
  let discoveryHandler=null;
  const discovery=new Map(),discoveryKey='guoban:library-discovery:v1';
  if (storage===undefined) {try {storage=globalThis.localStorage;} catch {storage=null;}}
  try {
    const saved=JSON.parse(storage?.getItem(exclusionKey)||'[]');
    if(Array.isArray(saved))for(const sid of saved)if(typeof sid==='string'&&/^\d{8,24}$/.test(sid))excluded.add(sid);
  } catch { /* Invalid preferences never block native membership. */ }
  try {
    const saved=JSON.parse(storage?.getItem(discoveryKey)||'[]');
    if(Array.isArray(saved))for(const row of saved.slice(-64))if(row&&typeof row.key==='string'&&/^(album|series):\d{8,24}$/.test(row.key)&&Array.isArray(row.items)&&Number.isFinite(row.retryAt))
      discovery.set(row.key,{...row,items:row.items.filter(item=>item&&typeof item.seriesId==='string'&&/^\d{8,24}$/.test(item.seriesId)&&typeof item.title==='string'&&Array.isArray(item.tags)&&Array.isArray(item.actors)).slice(0,120)});
  } catch { /* Search hints are expendable; native membership is not. */ }
  function discoveryIdentity(seed) {
    const album=relations.get(seed.seriesId)?.albumId;
    return album?'album:'+album:'series:'+seed.seriesId;
  }
  function discoveryRecord(seed) {
    return discovery.get(discoveryIdentity(seed))||discovery.get('series:'+seed.seriesId);
  }
  function rememberDiscovery(seed,items,complete) {
    const key=discoveryIdentity(seed),clean=items.slice(0,120).map(item=>({seriesId:item.seriesId,title:item.title,
      tags:item.tags||[],actors:item.actors||[],episodeCount:item.episodeCount||0,cover:'',intro:'',webAccessibleEpisodes:0}));
    discovery.delete('series:'+seed.seriesId);discovery.delete(key);
    discovery.set(key,{key,items:clean,complete:!!complete,retryAt:complete?0:Date.now()+30000});
    while(discovery.size>64)discovery.delete(discovery.keys().next().value);
    try{storage?.setItem(discoveryKey,JSON.stringify([...discovery.values()]));}
    catch{error='合集搜索记录暂时无法保存';notify();}
  }
  function discoveryLive(seed,start) {
    return members.favorites.has(seed.seriesId)&&!excluded.has(seed.seriesId)&&(removed.get(seed.seriesId)||0)<=start;
  }
  function rememberChoice(sid,value) {
    value?excluded.delete(sid):excluded.add(sid);
    try {storage?.setItem(exclusionKey,JSON.stringify([...excluded]));}
    catch {error='自动收藏的取消偏好暂时无法保存';}
  }
  function scheduleAutoFavorites() {
    autoDirty=true;
    if(autoWork||autoScheduled)return;
    autoScheduled=true;
    queueMicrotask(()=>{autoScheduled=false;void syncAutoFavorites();});
  }
  function syncAutoFavorites() {
    autoDirty=true;
    if(autoWork)return autoWork;
    autoWork=Promise.resolve().then(async()=>{
      do {
        autoDirty=false;
        await load();
        await ensure([...known.values()]);
        const groups=desktopLibraryGroups([...known.values()],relations,manual).filter(group=>group.items.length>1);
        if(!groups.length)continue;
        const existing=new Set((await original.favorites()).map(item=>item.seriesId));
        const start=revision;let changed=false;
        for(const group of groups)for(const item of group.items){
          const sid=item.seriesId;
          if(existing.has(sid)||excluded.has(sid)||(autoRetry.get(sid)||0)>Date.now())continue;
          let saved=false;
          try {
            await favorite(item,true,()=>{
              const key=manual.get(sid)||(relations.get(sid)?.albumId?'album:'+relations.get(sid).albumId:'series:'+sid);
              saved=known.has(sid)&&key===group.key&&!excluded.has(sid)&&!members.favorites.has(sid)&&(removed.get(sid)||0)<=start;
              return saved;
            },'auto');
            if(saved){existing.add(sid);autoRetry.delete(sid);changed=true;}
          } catch(caught){autoRetry.set(sid,Date.now()+30000);error=caught.message||'合集收藏暂时未完成';}
        }
        if(changed)notify('membership');
      } while(autoDirty);
    }).catch(caught=>{error=caught.message||'合集收藏暂时未完成';notify();})
      .finally(()=>{autoWork=null;if(autoDirty)scheduleAutoFavorites();});
    return autoWork;
  }
  const original = {favorite:api.setFavorite.bind(api), favorites:api.favorites.bind(api), history:api.history.bind(api)};
  async function request(path = '', body, onProgress) {
    const status = await api.validationStatus(), url = new URL(status.baseUrl);
    if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || !url.port || url.username || url.password || url.pathname !== '/' || url.search || url.hash)
      throw Error('归组服务暂不可用');
    if (body !== undefined && access?.origin !== url.origin) await load(true);
    const abort = new AbortController(), timer = setTimeout(() => abort.abort(), 45000);
    try {
      const response = await fetch(url.origin + '/desktop/library' + path, {
        method:body === undefined ? 'GET' : 'POST', body:body === undefined ? undefined : JSON.stringify(body),
        headers:{'x-desktop-library-client':'1', 'x-desktop-library-token':access?.token || '', 'content-type':'application/json'},
        credentials:'omit', redirect:'error', cache:'no-store', signal:abort.signal
      });
      if (!response.ok) {if (response.status === 401) access = null; throw Error('归组信息加载失败，收藏不受影响');}
      if (onProgress && response.headers.get('content-type')?.includes('application/x-ndjson'))
        return await desktopReadPosterStream(response,onProgress);
      const result = await response.json();
      if (result.requestToken) access = {origin:url.origin, token:result.requestToken};
      return result;
    } finally {clearTimeout(timer);}
  }
  function accept(value) {
    for (const row of value.relations || []) if (/^\d{8,24}$/.test(row.seriesId) &&
      (row.albumId === null || typeof row.albumId === 'string' && /^\d{8,24}$/.test(row.albumId))) relations.set(row.seriesId, row);
    if (value.manual) {manual.clear(); for (const [sid,key] of Object.entries(value.manual)) manual.set(sid,key);}
    notify();scheduleAutoFavorites();
  }
  function load(force = false) {
    if (loading) return loading;
    if (access && !force) return Promise.resolve();
    loading = request().then(value => {accept(value); error='';}).finally(() => {loading=null;});
    return loading;
  }
  async function drain() {
    if (draining) return;
    draining = true;
    try {
      await load();
      while ([...pending.values()].some(entry => !entry.running)) {
        const now = Date.now()/1000;
        const entries = [...pending].filter(([,entry]) => !entry.running).slice(0,20);
        for (const [,entry] of entries) entry.running = true;
        const todo = entries.filter(([sid]) => !relations.has(sid) || relations.get(sid).retryAt && relations.get(sid).retryAt <= now);
        if (todo.length) {accept(await request('/relations', {seriesIds:todo.map(([sid])=>sid)})); error='';}
        for (const [sid,entry] of entries) {pending.delete(sid); entry.resolve(relations.get(sid));}
      }
    } catch (caught) {
      error = caught.message || '归组信息暂不可用';
      for (const [sid,entry] of pending) {pending.delete(sid); entry.resolve(relations.get(sid));}
    } finally {draining=false; notify();}
  }
  function ensure(items) {
    const promises = [];
    for (const item of items) {
      const sid = typeof item === 'string' ? item : item.seriesId;
      if (typeof sid !== 'string' || !/^\d{8,24}$/.test(sid)) continue;
      const row=relations.get(sid);
      if (row && (!row.retryAt || row.retryAt > Date.now()/1000)) {promises.push(Promise.resolve(row)); continue;}
      if (!pending.has(sid)) {
        let resolve; const promise = new Promise(done=>{resolve=done;});
        pending.set(sid,{promise,resolve,running:false});
      }
      promises.push(pending.get(sid).promise);
    }
    if (pending.size) queueMicrotask(drain);
    return Promise.all(promises);
  }
  function favorite(item, value, guard = () => true, origin = 'user') {
    const sid=item.seriesId;
    const choice=origin==='user'?(choices.get(sid)||0)+1:choices.get(sid);
    if(origin==='user')choices.set(sid,choice);
    if(origin==='user')rememberChoice(sid,value);
    if (!value) removed.set(sid,++revision);
    const previous=writes.get(sid) || Promise.resolve();
    const write=previous.catch(()=>{}).then(async()=>{
      if (!guard()) return false;
      const result=await original.favorite(item,value);
      if (value) {members.favorites.add(sid);known.set(sid,item);void ensure([item]);}
      else {members.favorites.delete(sid);if(!members.history.has(sid))known.delete(sid);}
      if(origin!=='auto')scheduleAutoFavorites();
      if(origin==='user'&&value&&discoveryHandler) {
        const start=revision;
        queueMicrotask(()=>{void Promise.resolve().then(()=>discoveryHandler(item,()=>choices.get(sid)===choice&&discoveryLive(item,start)))
          .catch(caught=>{error=caught.message||'合集后台搜索暂未完成';notify();});});
      }
      return result;
    });
    writes.set(sid,write);
    write.then(()=>{if(writes.get(sid)===write)writes.delete(sid);},()=>{if(writes.get(sid)===write)writes.delete(sid);});
    return write;
  }
  async function setManual(sid,targetId) {await load(); accept(await request('/manual',{seriesId:sid,targetId}));}
  function observe(items,kind) {
    members[kind]=new Set(items.map(item=>item.seriesId));
    for(const item of items)known.set(item.seriesId,item);
    for(const sid of known.keys())if(!members.favorites.has(sid)&&!members.history.has(sid))known.delete(sid);
    return ensure(items).then(value=>{scheduleAutoFavorites();return value;});
  }
  function recordDiscovery(seed,result) {
    const album=relations.get(seed.seriesId)?.albumId;
    const candidates=[seed,...result.items];
    const confirmed=candidates.filter(item=>album&&relations.get(item.seriesId)?.albumId===album);
    const incomplete=!!result.incomplete||candidates.some(item=>relations.get(item.seriesId)?.state==='failed');
    rememberDiscovery(seed,confirmed,!incomplete);
    return {...result,incomplete};
  }
  async function collect(seed, find, live, progress = () => {}) {
    const start=revision;
    progress('正在查找其他季…');
    const result=await find();
    if (!live()) throw desktopLibraryCancelled();
    const candidates=[...new Map([seed,...result.items].map(item=>[item.seriesId,item])).values()];
    progress(`正在核验 ${candidates.length} 个候选…`);
    await ensure(candidates);
    if (!live()) throw desktopLibraryCancelled();
    const cachedResult=recordDiscovery(seed,result);
    const album=relations.get(seed.seriesId)?.albumId;
    const verified=candidates.filter(item => item.seriesId===seed.seriesId || album && relations.get(item.seriesId)?.albumId===album);
    const uncertain=candidates.filter(item => item.seriesId!==seed.seriesId && (!album || !relations.get(item.seriesId)?.albumId));
    const existing=new Set((await original.favorites()).map(item=>item.seriesId)); let added=0, skipped=0;
    for (const item of verified) {
      if (!live()) throw desktopLibraryCancelled();
      if (existing.has(item.seriesId) || excluded.has(item.seriesId) || (removed.get(item.seriesId)||0)>start) {skipped++; continue;}
      let saved=false;
      await favorite(item,true,()=>{saved=live() && !excluded.has(item.seriesId) && (removed.get(item.seriesId)||0)<=start; return saved;},'collect');
      if (saved) {added++;existing.add(item.seriesId);progress(`已收藏 ${added} 季…`);}
    }
    return {added,skipped,uncertain,incomplete:cachedResult.incomplete,verified:verified.length};
  }
  return {relations,manual,known,ensure,observe,favorite,setManual,collect,load,request,syncAutoFavorites,
    discoveryIdentity,discoveryRecord,rememberDiscovery,recordDiscovery,
    setDiscoveryHandler(handler){discoveryHandler=handler;},
    get catalog(){return [...new Map([...discovery.values()].flatMap(row=>row.items).concat([...known.values()]).map(item=>[item.seriesId,item])).values()];},
    get error(){return error;}, get pendingCount(){return pending.size;}, original};
}

export {DesktopSearchQueue, desktopLibraryCancelled, desktopLibraryGroups, desktopLibrarySortSeasons, desktopLibrarySortGroups, desktopLibraryPage, desktopLibraryProgress, desktopLibraryNext, desktopCreateLibrary};
