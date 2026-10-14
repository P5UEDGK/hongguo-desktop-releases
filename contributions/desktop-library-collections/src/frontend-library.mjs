import {parseSeasonTitle, findOtherSeasons as defaultFindOtherSeasons, findNextSeason as defaultFindNextSeason} from './season-search.mjs';
import { DesktopSearchQueue, desktopLibraryCancelled, desktopLibraryGroups, desktopLibrarySortSeasons, desktopLibrarySortGroups, desktopLibraryPage, desktopLibraryProgress, desktopLibraryNext, desktopCreateLibrary } from './library-core.mjs';

// Initialize once before mounting the host. All application APIs stay host-owned.
export function createLibraryUI({React, jsxRuntime, api, parseSeason=parseSeasonTitle, findOtherSeasons=defaultFindOtherSeasons, findNextSeason=defaultFindNextSeason, Cover, coverFallback}) {
  const O=React, b=jsxRuntime, ge=api, Ts=parseSeason, KR=findOtherSeasons, qR=findNextSeason, O0=Cover, P0=coverFallback;
function desktopLibraryNotify(kind) {window.dispatchEvent(new Event(kind==='membership'?'desktoplibrarymembership':'desktoplibrarychange'));}
const desktopSearchQueue = new DesktopSearchQueue(desktopLibraryNotify);
const desktopLibrary = desktopCreateLibrary(ge,desktopLibraryNotify);
function desktopUseLibraryVersion() {
  const [,update]=O.useState(0);
  O.useEffect(()=>{const changed=()=>update(value=>value+1);window.addEventListener('desktoplibrarychange',changed);return()=>window.removeEventListener('desktoplibrarychange',changed);},[]);
}

function desktopSeasonProxy(api,context,check=()=>true) {
  return {...api,
    searchNovelfm:(...args)=>context.request(()=>desktopRawSearch.searchNovelfm(...args)),
    resolveSeasonCandidates:async(seed,candidates,live=()=>true)=>{
      if(!context.live()||!check()||!live())return {items:[],verified:false};
      await desktopLibrary.ensure([seed,...candidates]);
      if(!context.live()||!check()||!live())return {items:[],verified:false};
      const album=desktopLibrary.relations.get(seed.seriesId)?.albumId;
      const items=candidates.filter(item=>!album||!desktopLibrary.relations.get(item.seriesId)?.albumId||desktopLibrary.relations.get(item.seriesId).albumId===album);
      return {items,verified:!!album&&items.some(item=>desktopLibrary.relations.get(item.seriesId)?.albumId===album)};
    }
  };
}

function desktopSeasonSearch(api,item,check,find,label) {
  if(find===qR)return desktopFindNextSeason(api,item,check);
  return desktopSeasonTask(item,{live:check,force:true});
}

const desktopDiscoveryRequests = new Map();
async function desktopSeasonTask(item,{live=()=>true,progress=()=>{},save=false,background=false,force=false}={}) {
  await desktopLibrary.ensure([item]);
  if(!live())throw desktopLibraryCancelled();
  const key=desktopLibrary.discoveryIdentity(item),taskKey='seasons:'+key;
  let request=desktopDiscoveryRequests.get(key);
  if(!request){request={consumers:new Set(),work:null,force:false};desktopDiscoveryRequests.set(key,request);}
  request.consumers.add({item,live,progress,save});request.force ||= force;
  if(request.work) {
    if(!background)desktopSearchQueue.run(taskKey,'查找各季：'+item.title,()=>{}, {background:false});
    return request.work;
  }
  request.work=desktopSearchQueue.run(taskKey,(background?'后台补齐合集：':'查找各季：')+item.title,async context=>{
    const consumers=()=>[...request.consumers].filter(row=>row.live());
    const check=()=>context.live()&&consumers().length>0;
    const report=text=>{for(const row of consumers())row.progress(text);};
    if(!check())throw desktopLibraryCancelled();
    item=consumers()[0].item;
    const cached=desktopLibrary.discoveryRecord(item);
    let found;
    if(!request.force&&cached&&(cached.complete||cached.retryAt>Date.now())) {
      found={items:cached.items,incomplete:!cached.complete,automatic:false};
    } else {
      report('正在查找其他季…');
      const proxy=desktopSeasonProxy(ge,context,check);
      // KR is the existing 查找并收藏各季 finder, including its punctuation
      // fallback, pagination, 30-second budget and relationship verification.
      found=await KR(proxy,item,check);
      if(!check())throw desktopLibraryCancelled();
      await desktopLibrary.ensure([item,...found.items]);
      if(!check())throw desktopLibraryCancelled();
      found=desktopLibrary.recordDiscovery(item,found);
    }
    let collection=null;
    if(consumers().some(row=>row.save)) {
      collection=await desktopLibrary.collect(item,async()=>found,
        ()=>context.live()&&consumers().some(row=>row.save),report);
    }
    return {...found,collection};
  },{background}).finally(()=>{
    if(desktopDiscoveryRequests.get(key)===request)desktopDiscoveryRequests.delete(key);
    desktopLibraryNotify('membership');
  });
  return request.work;
}

async function desktopCollectSeasons(item,{live=()=>true,progress=()=>{},background=false,force=!background}={}) {
  const result=await desktopSeasonTask(item,{live,progress,save:true,background,force});
  if(!live())throw desktopLibraryCancelled();
  return result.collection;
}

async function desktopFindNextSeason(api,item,check) {
  await desktopLibrary.ensure([item]);
  if(!check())return {items:[],automatic:false,incomplete:true};
  let result=desktopLibraryNext(item,desktopLibrary.catalog,desktopLibrary.relations);
  if(!result.items.length) {
    const found=await desktopSeasonTask(item,{live:check});
    if(!check())return {items:[],automatic:false,incomplete:true};
    result={...desktopLibraryNext(item,found.items,desktopLibrary.relations),incomplete:found.incomplete};
  }
  const rows=[];let incomplete=!!result.incomplete;
  for(const candidate of result.items.slice(0,5)) {
    if(!check())return {items:[],automatic:false,incomplete:true};
    try {
      const detail=await api.validationEpisodes(candidate.seriesId);
      if(!check())return {items:[],automatic:false,incomplete:true};
      if(detail.seriesId!==candidate.seriesId||!Number.isSafeInteger(detail.total)||detail.total<1||detail.total>100000||!Array.isArray(detail.episodes)||!detail.episodes.includes(1)) {incomplete=true;continue;}
      rows.push({...candidate,episodeCount:detail.total});
    } catch {incomplete=true;}
  }
  return {items:rows,incomplete,automatic:!incomplete&&result.automatic&&rows.length===1};
}

async function desktopDiscoverFavorite(item,live) {
  if(!live()||!Ts(item.title))return;
  return desktopCollectSeasons(item,{live,background:true});
}
const desktopRawSearch = {};
for (const name of ['search','searchExplorer','searchNovelfm','validationSearch']) {
  if (!ge[name]) continue;
  desktopRawSearch[name]=ge[name].bind(ge);
  ge[name]=(...args)=>desktopSearchQueue.run(name+':'+JSON.stringify(args),'搜索：'+String(args[0]||''),
    context=>context.request(()=>desktopRawSearch[name](...args)));
}
ge.setFavorite=(item,value)=>desktopLibrary.favorite(item,value);
for (const name of ['favorites','history']) {
  ge[name]=async()=>{const items=await desktopLibrary.original[name]();void desktopLibrary.observe(items,name);return items;};
}

desktopLibrary.setDiscoveryHandler(desktopDiscoverFavorite);

function DesktopCoverLabels({kind,progress}) {
  return b.jsxs(O.Fragment,{children:[
    b.jsx('span',{className:'desktop-kind-chip'+(kind==='合集'?' is-collection':''),children:kind}),
    progress&&b.jsx('span',{className:'desktop-watch-chip',title:progress.title,children:progress.label})
  ]});
}

function DesktopLibraryPagination({total,page,size,onChange,label}) {
  const value=desktopLibraryPage(Array(total),page,size);
  if(value.pages<=1)return null;
  return b.jsxs('nav',{className:'desktop-library-pagination','aria-label':label,children:[
    b.jsx('button',{type:'button',disabled:value.page===1,onClick:()=>onChange(value.page-1),'aria-label':label+'上一页',children:'上一页'}),
    b.jsxs('label',{children:['第 ',b.jsx('select',{'aria-label':label+'页码',value:value.page,onChange:event=>onChange(Number(event.target.value)),children:Array.from({length:value.pages},(_,i)=>b.jsx('option',{value:i+1,children:i+1},i+1))}),` / ${value.pages} 页`]}),
    b.jsx('button',{type:'button',disabled:value.page===value.pages,onClick:()=>onChange(value.page+1),'aria-label':label+'下一页',children:'下一页'})
  ]});
}

function DesktopSeasonActions({series,disabled=false}) {
  desktopUseLibraryVersion();
  const [busy,setBusy]=O.useState(false),[message,setMessage]=O.useState(''),[uncertain,setUncertain]=O.useState([]);
  const [candidatePage,setCandidatePage]=O.useState(1);
  const candidates=desktopLibraryPage(uncertain,candidatePage,8);
  O.useEffect(()=>{if(candidatePage!==candidates.page)setCandidatePage(candidates.page);},[candidates.page,candidatePage]);
  const mounted=O.useRef(true);
  O.useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
  const parsed=Ts(series.title);
  const search=desktopSearchQueue.state();
  const status=(busy&&search.cancelled?'正在结束搜索，等待当前请求返回…':message||(parsed?'搜索可能漏季，可自行搜索后收藏':'当前标题暂不支持自动匹配，可自行搜索其他季后收藏'))+(busy&&search.waiting?` · 等待 ${search.waiting} 项`:'');
  async function collect() {
    if (busy) return;
    setBusy(true);setMessage('等待搜索…');setUncertain([]);setCandidatePage(1);
    try {
      const result=await desktopCollectSeasons(series,{
        live:()=>mounted.current,
        progress:text=>{if(mounted.current)setMessage(text);}
      });
      if(mounted.current){setUncertain(result.uncertain);setMessage(`已加入 ${result.added} 季，跳过 ${result.skipped} 季；找到并确认 ${result.verified} 季${result.incomplete?'，搜索可能未完成':''}。可手动搜索补齐。`);}
    } catch(error) {if(mounted.current)setMessage(error.message);}
    finally {window.dispatchEvent(new Event('desktoplibrarymembership'));if(mounted.current)setBusy(false);}
  }
  async function addCandidate(item) {
    setBusy(true);
    try {await ge.setFavorite(item,true);window.dispatchEvent(new Event('desktoplibrarymembership'));setUncertain(rows=>rows.filter(row=>row.seriesId!==item.seriesId));setMessage('已收藏所选季；关系未确认时保持独立');}
    catch(error){setMessage(error.message);}
    finally{setBusy(false);}
  }
  return b.jsxs('div',{className:'desktop-season-actions','aria-label':'分季收藏',children:[
    b.jsxs('div',{className:'desktop-season-toolbar',children:[
      parsed&&b.jsx('button',{type:'button',className:'secondary',disabled:disabled||busy,onClick:()=>void collect(),children:'查找并收藏各季'}),
      b.jsx('small',{className:'desktop-season-message',role:'status','aria-live':'polite','aria-atomic':true,title:status,children:status}),
      busy&&search.label&&b.jsx('button',{type:'button',className:'desktop-season-cancel',disabled:search.cancelled,onClick:()=>desktopSearchQueue.cancel(),children:'取消搜索'})
    ]}),
    candidates.items.map(item=>b.jsxs('div',{className:'desktop-season-candidate',children:[b.jsx('span',{children:item.title+' · 系列关系待确认'}),b.jsx('button',{type:'button',disabled:busy||disabled,onClick:()=>void addCandidate(item),children:'收藏此季'})]},item.seriesId)),
    b.jsx(DesktopLibraryPagination,{total:uncertain.length,page:candidates.page,size:8,onChange:setCandidatePage,label:'待确认候选'})
  ]});
}

function desktopLibraryDisplayTitle(title) {
  const base=Ts(title)?.base||title;
  return base.replace(/[\s:：]+$/u,'').trim()||base;
}

function desktopLibrarySortPreference(name,value) {
  const key='guoban:library-sort:v1',allowed=name==='seasons'?['asc','desc']:
    name==='favorites'?['recent','played']:['recent','title-asc','title-desc'];
  const fallback=name==='seasons'?'desc':'recent';
  try {
    const saved=JSON.parse(localStorage.getItem(key)||'{}');
    const preferences=saved&&typeof saved==='object'&&!Array.isArray(saved)?saved:{};
    if(value!==undefined&&allowed.includes(value)){preferences[name]=value;localStorage.setItem(key,JSON.stringify(preferences));return value;}
    return allowed.includes(preferences[name])?preferences[name]:fallback;
  } catch {return value!==undefined&&allowed.includes(value)?value:fallback;}
}

function DesktopLibrarySort({value,onChange,seasons=false,view}) {
  const label=seasons?'合集季号排序':view==='history'?'历史排序':'收藏排序';
  const options=seasons?[['desc','季号倒序'],['asc','季号正序']]:view==='history'?[
    ['recent','最近观看'],['title-asc','名称正序'],['title-desc','名称倒序']
  ]:[['played','最近播放'],['recent','最近添加']];
  return b.jsx('label',{className:'desktop-library-sort',children:b.jsx('select',{
    'aria-label':label,value,onChange:event=>onChange(event.target.value),
    children:options.map(([key,text])=>b.jsx('option',{value:key,children:text},key))
  })});
}

function DesktopLibraryGrid({items,history=[],view,renderCard}) {
  desktopUseLibraryVersion();
  const [selected,setSelected]=O.useState(null),[visibleCounts,setVisibleCounts]=O.useState({});
  const [rootOrder,setRootOrder]=O.useState(()=>desktopLibrarySortPreference(view));
  const [seasonOrder,setSeasonOrder]=O.useState(()=>desktopLibrarySortPreference('seasons'));
  O.useEffect(()=>{setRootOrder(desktopLibrarySortPreference(view));setSeasonOrder(desktopLibrarySortPreference('seasons'));setSelected(null);restoreKey.current=null;rootScroll.current=0;},[view]);
  const heading=O.useRef(null),restoreKey=O.useRef(null),rootScroll=O.useRef(0),loadMore=O.useRef(null);
  const signature=items.map(item=>item.seriesId).join(',');
  O.useEffect(()=>{void desktopLibrary.ensure(items);},[signature]);
  const groups=desktopLibraryGroups(items,desktopLibrary.relations,desktopLibrary.manual,[...desktopLibrary.known.values()]);
  // The album key may arrive asynchronously. Keep navigation and task state
  // attached to the selected member while its visible group grows or changes key.
  const collection=selected?groups.find(group=>group.items.some(item=>item.seriesId===selected)):null;
  const sortedGroups=desktopLibrarySortGroups(groups,items,rootOrder,group=>group.items.length>1?desktopLibraryDisplayTitle(group.items[0].title):group.items[0].title,history);
  const visibleCount=visibleCounts[view]||12,roots=sortedGroups.slice(0,visibleCount);
  const hasMore=roots.length<sortedGroups.length,seasons=desktopLibrarySortSeasons(collection?.items||[],desktopLibrary.relations,seasonOrder);
  function appendRoots(){setVisibleCounts(counts=>({...counts,[view]:Math.min(sortedGroups.length,(counts[view]||12)+12)}));}
  O.useEffect(()=>{
    if(collection||!hasMore||!loadMore.current||typeof IntersectionObserver==='undefined')return;
    let appended=false;
    const observer=new IntersectionObserver(entries=>{
      if(!appended&&entries.some(entry=>entry.isIntersecting)){appended=true;appendRoots();}
    },{rootMargin:'0px 0px 480px 0px'});
    observer.observe(loadMore.current);
    return()=>observer.disconnect();
  },[!!collection,hasMore,visibleCount,sortedGroups.length,rootOrder,view]);
  O.useEffect(()=>{if(selected&&!collection)setSelected(null);},[selected,!!collection]);
  O.useEffect(()=>{
    if(selected&&collection){heading.current?.focus({preventScroll:true});heading.current?.closest('.desktop-collection-view')?.scrollIntoView({block:'start'});}
    else if(restoreKey.current){
      const restoredGroup=groups.find(group=>group.items.some(item=>item.seriesId===restoreKey.current));
      [...document.querySelectorAll('[data-collection-key]')].find(node=>node.getAttribute('data-collection-key')===restoredGroup?.key)?.focus({preventScroll:true});
      window.scrollTo(0,rootScroll.current);restoreKey.current=null;
    }
  },[selected]);
  function enter(group){rootScroll.current=window.scrollY;restoreKey.current=group.items[0].seriesId;setSelected(group.items[0].seriesId);}
  const label=view==='history'?'观看历史':'我的收藏';
  function renderSeason(item) {
    const card=renderCard(item);
    return view==='history'&&!history.some(row=>row.seriesId===item.seriesId)
      ?O.cloneElement(card,{reason:'未观看',onRemoveHistory:undefined}):card;
  }
  if(collection){
    const first=collection.items.find(item=>item.seriesId===selected),title=desktopLibraryDisplayTitle(first.title);
    const kind=collection.items.length>1?'合集':'系列';
    return b.jsxs('section',{className:'desktop-collection-view','aria-label':title+kind,children:[
      b.jsxs('nav',{className:'desktop-library-breadcrumb','aria-label':'合集导航',children:[
        b.jsx('button',{type:'button',onClick:()=>setSelected(null),children:'← 返回'+label}),b.jsx('span',{children:kind})
      ]}),
      b.jsxs('header',{className:'desktop-collection-heading',children:[
        b.jsx('h1',{ref:heading,tabIndex:-1,children:title}),b.jsx('span',{children:`共 ${collection.items.length} 季`}),
        b.jsx(DesktopLibrarySort,{seasons:true,value:seasonOrder,onChange:value=>{setSeasonOrder(value);desktopLibrarySortPreference('seasons',value);heading.current?.closest('.desktop-collection-view')?.scrollIntoView({block:'start'});}})
      ]}),
      b.jsx(DesktopSeasonActions,{series:first},selected),
      b.jsx('div',{className:'series-grid desktop-library-grid desktop-season-grid',children:seasons.map(renderSeason)})
    ]});
  }
  return b.jsxs('div',{className:'desktop-library-root',children:[
    b.jsxs('div',{className:'desktop-library-toolbar',children:[b.jsx('span',{children:`${groups.length} 个条目，其中 ${groups.filter(group=>group.items.length>1).length} 个合集`}),
      b.jsx(DesktopLibrarySort,{view,value:rootOrder,onChange:value=>{setRootOrder(value);desktopLibrarySortPreference(view,value);setVisibleCounts(counts=>({...counts,[view]:12}));window.scrollTo(0,0);}})
    ]}),
    b.jsx('div',{className:'series-grid desktop-library-grid',children:roots.map(group=>{
      if(group.items.length===1)return renderCard(group.items[0],{open:()=>enter(group),entryKey:group.key});
      const first=group.items[0],title=desktopLibraryDisplayTitle(first.title);
      const progress=desktopLibraryProgress(group.items,history,desktopLibrary.relations);
      return b.jsxs('article',{className:'series-card desktop-series-folder','aria-label':title+'合集',children:[
        b.jsxs('button',{type:'button',className:'cover-button desktop-folder-button desktop-series-entry','data-collection-key':group.key,'aria-label':`进入系列：${title}，${group.items.length} 季`,onClick:()=>enter(group),children:[
          b.jsx(O0,{item:first,fallback:P0,lazy:true}),b.jsx('span',{className:'cover-shade'}),b.jsx(DesktopCoverLabels,{kind:'合集',progress}),
          b.jsx('span',{className:'desktop-season-count',children:group.items.length+' 季'})
        ]}),
        b.jsx('div',{className:'card-copy',children:b.jsx('button',{className:'card-title',title,onClick:()=>enter(group),children:title})})
      ]},group.key);
    })}),
    hasMore&&b.jsx('div',{className:'desktop-library-more',ref:loadMore,children:
      b.jsx('button',{type:'button',onClick:appendRoots,children:'加载更多'})})
  ]});
}

const desktopLibraryStyle = document.createElement('style');
desktopLibraryStyle.textContent = `
.desktop-library-grid{--library-accent:var(--coral,#ff6697);--library-muted:#626975;--library-border:var(--border,#e6e7ec);--library-surface:#fff;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:24px 18px}
.desktop-library-sort{position:relative;display:inline-flex;flex:none;font-size:13px;white-space:nowrap;color:var(--muted,#626975)}.desktop-library-sort::after{content:"";position:absolute;right:13px;top:50%;width:6px;height:6px;border-right:1.5px solid currentColor;border-bottom:1.5px solid currentColor;transform:translateY(-70%) rotate(45deg);pointer-events:none}.desktop-library-sort select{appearance:none;font:inherit;line-height:1.4;min-width:112px;min-height:36px;box-sizing:border-box;padding:8px 34px 8px 12px;border:1px solid var(--line,#e6e7ec);border-radius:10px;background:var(--paper,#fff);color:var(--ink,#414754);cursor:pointer;box-shadow:none}.desktop-library-sort select:hover{border-color:var(--coral,#b82d5c)}.desktop-library-sort select:focus-visible{outline:2px solid var(--coral,#b82d5c);outline-offset:3px}.desktop-library-sort select option{background:var(--paper,#fff);color:var(--ink,#414754)}.desktop-collection-heading .desktop-library-sort{margin-left:auto}.desktop-library-toolbar{flex-wrap:wrap;align-items:center}
.desktop-library-more{display:flex;justify-content:center;margin:26px 0 12px}.desktop-library-more button{font:inherit;font-size:13px;min-height:36px;padding:8px 18px;border:1px solid var(--line,#e6e7ec);border-radius:10px;background:var(--paper,#fff);color:var(--ink,#414754);cursor:pointer}.desktop-library-more button:hover{border-color:var(--coral,#b82d5c)}
.desktop-library-grid .series-card{min-width:0;align-self:start}.desktop-library-grid .cover-button{aspect-ratio:3/4;border-radius:12px;box-shadow:none}.desktop-library-grid .card-copy{padding-top:10px}.desktop-library-grid .card-title{white-space:normal;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;text-align:left;font-size:15px;line-height:1.45;min-height:2.9em;font-weight:600;overflow-wrap:anywhere;text-wrap:balance}.desktop-library-grid .card-copy p{font-size:12px;line-height:1.5;color:var(--library-muted);margin-top:5px}.desktop-library-grid .episode-chip{top:auto;bottom:10px;left:10px;right:auto;font-size:11px;max-width:40%}.desktop-kind-chip,.desktop-watch-chip,.desktop-season-count{position:absolute;z-index:2;max-width:calc(100% - 20px);padding:4px 7px;border-radius:6px;font-size:11px;line-height:1.5;font-weight:600;color:#fff;background:#20242acc;pointer-events:none}.desktop-kind-chip{top:10px;left:10px}.desktop-kind-chip.is-collection{background:#ad2352}.desktop-watch-chip{right:10px;bottom:10px;box-sizing:border-box;height:24px;padding:4px 7px;font-size:11px;line-height:16px;text-align:right;white-space:nowrap;max-width:calc(100% - 20px);overflow:hidden;text-overflow:ellipsis;background:#20242a66;text-shadow:0 1px 2px #0008}.desktop-season-count{top:10px;right:10px;background:#fff;color:#95324f}.desktop-series-folder{border:0;background:transparent;padding:0}.desktop-folder-button{outline:2px solid #ffd4e3;outline-offset:3px}.desktop-series-folder .card-title{padding-right:0}
.desktop-season-actions button,.desktop-library-pagination button,.desktop-library-pagination select,.desktop-library-breadcrumb button{font:inherit;border:1px solid var(--border,#e6e7ec);border-radius:8px;background:#fff;color:#414754;padding:7px 12px;cursor:pointer}.desktop-season-actions button:hover,.desktop-library-pagination button:not(:disabled):hover,.desktop-library-breadcrumb button:hover{background:#fff1f6;border-color:#efb6ca}.desktop-library-pagination button:disabled,.desktop-season-actions button:disabled{opacity:.45;cursor:default}.desktop-library-root button:focus-visible,.desktop-collection-view button:focus-visible,.desktop-library-pagination select:focus-visible{outline:2px solid #b82d5c;outline-offset:3px}.desktop-collection-heading h1:focus{outline:none}
.desktop-season-actions{margin:14px 0 22px;font-size:13px}.desktop-season-toolbar{display:flex;align-items:center;gap:12px;min-width:0}.desktop-season-toolbar>button{flex:none}.desktop-season-toolbar>.desktop-season-message{flex:1;min-width:0;margin:0;color:#626975;font-size:12px;line-height:1.6;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.desktop-season-candidate{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:10px}.desktop-season-candidate{padding:10px 0;border-bottom:1px solid #e6e7ec}.desktop-season-candidate>span{flex:1;min-width:160px}.desktop-library-pagination{display:flex;justify-content:center;align-items:center;gap:14px;flex-wrap:wrap;margin:26px 0 12px;font-size:13px;color:#626975}.desktop-library-pagination select{padding:6px;min-width:50px}.desktop-library-toolbar{display:flex;justify-content:space-between;align-items:start;gap:16px;margin:-8px 0 22px;color:#626975;font-size:13px}.desktop-collection-view{scroll-margin-top:96px}.desktop-library-breadcrumb{display:flex;align-items:center;gap:14px;margin-bottom:18px;font-size:13px;color:#626975}.desktop-library-breadcrumb button{border:0;padding:5px 0;color:#a52c54;background:transparent}.desktop-collection-heading{display:flex;align-items:baseline;flex-wrap:wrap;gap:12px}.desktop-collection-heading h1{margin:0;font-size:26px;line-height:1.4;overflow-wrap:anywhere;text-wrap:balance}.desktop-collection-heading>span{font-size:13px;color:#626975}.library-page:has(.desktop-collection-view)>.headline-row{display:none}
@media(min-width:1500px){.desktop-library-grid{grid-template-columns:repeat(auto-fill,minmax(180px,1fr))}}@media(max-width:700px){.desktop-library-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:20px 14px}.desktop-library-grid .card-title{font-size:14px}.desktop-kind-chip,.desktop-season-count{font-size:10px;padding:3px 5px}.desktop-watch-chip{right:6px;bottom:6px}.desktop-library-grid .episode-chip{left:6px;bottom:6px;font-size:10px}.desktop-library-toolbar{align-items:center}.desktop-collection-heading h1{font-size:23px}}
`;
document.head.append(desktopLibraryStyle);

  return {LibraryGrid:DesktopLibraryGrid, CoverLabels:DesktopCoverLabels,
    SeasonActions:DesktopSeasonActions, seasonSearch:desktopSeasonSearch, collectSeasons:desktopCollectSeasons, collectSeasons:desktopCollectSeasons, collectSeasons:desktopCollectSeasons, collectSeasons:desktopCollectSeasons,
    progress:desktopLibraryProgress, library:desktopLibrary, searchQueue:desktopSearchQueue};
}
