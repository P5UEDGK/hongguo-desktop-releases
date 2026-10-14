import assert from 'node:assert/strict';
import {createLibraryUI} from '../src/frontend-library.mjs';
const events=new EventTarget(), styles=[];
globalThis.window=events;
globalThis.document={createElement:()=>({}),head:{append:style=>styles.push(style)}};
const defer=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve};};
const pending=defer(), seen=[], favorites=[];
const SID='7673807696302197784';
const item={seriesId:SID,title:'测试第九季',episodeCount:100};
const api={
  search:async text=>{seen.push('search:'+text);return pending.promise;},
  searchNovelfm:async text=>{seen.push('season:'+text);return {items:[]};},
  setFavorite:async(row,value)=>{favorites.push([row.seriesId,value]);},
  favorites:async()=>[item], history:async()=>[],
  validationStatus:async()=>({baseUrl:'http://127.0.0.1:12345'})
};
globalThis.fetch=async(url,options)=>({ok:true,json:async()=>options.method==='GET'
  ? {relations:[{seriesId:SID,albumId:'7619198149772446782',season:9,retryAt:0}],manual:{},requestToken:'fixture'}
  : {relations:[]}});
const jsxRuntime={jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})};
const React={Fragment:Symbol('Fragment'),useState:value=>[value,()=>{}],useRef:value=>({current:value}),useEffect:()=>{}};
const Cover=()=>null;
const ui=createLibraryUI({React,jsxRuntime,api,parseSeason:()=>({base:'测试'}),findOtherSeasons:()=>{throw Error('navigation must not search');},Cover,coverFallback:'fixture'});
assert.equal(styles.length,1);
assert.ok(styles[0].textContent.includes('.desktop-season-toolbar'));
for(const name of ['LibraryGrid','CoverLabels','SeasonActions','seasonSearch','progress'])assert.equal(typeof ui[name],'function');
console.log('PASS explicit host factory installs one stylesheet and exposes components');
const labels=ui.CoverLabels({kind:'合集',progress:{title:'最近观看',label:'第 9 季 · 已看 50%'}});
assert.equal(labels.props.children[1].props.children,'第 9 季 · 已看 50%');
const grid=ui.LibraryGrid({items:[item],history:[],view:'favorites',renderCard:(row,navigation)=>({row,navigation})});
const card=grid.props.children[1].props.children[0];
assert.equal(card.row.seriesId,SID);assert.equal(typeof card.navigation.open,'function');
assert.equal(seen.length,0);
console.log('PASS root singleton uses series navigation without starting a search');
let notified=0;events.addEventListener('desktoplibrarychange',()=>notified++);
const first=api.search('first');
const caught=first.catch(error=>error.message);
await new Promise(resolve=>setImmediate(resolve));
const second=api.searchNovelfm('later');
assert.deepEqual(seen,['search:first']);
ui.searchQueue.cancel();
assert.equal(await second.catch(error=>error.message),'搜索已取消');
const third=api.searchNovelfm('after-cancel');
await new Promise(resolve=>setImmediate(resolve));
assert.deepEqual(seen,['search:first']);
pending.resolve({items:[]});
assert.equal(await caught,'搜索已取消');
await third;
assert.deepEqual(seen,['search:first','season:after-cancel']);
assert.ok(notified>0);
console.log('PASS host search wrappers share the queue and preserve the in-flight slot on cancel');
await api.setFavorite(item,true);await api.setFavorite(item,false);await api.setFavorite(item,true);
assert.deepEqual(favorites,[[SID,true],[SID,false],[SID,true]]);
await api.favorites();await ui.library.ensure([item]);
assert.equal(ui.library.relations.get(SID).season,9);
assert.equal(ui.progress([item],[{...item,lastEpisode:50}]).percent,50);
console.log('PASS host membership remains native-owned and metadata uses the shared relation cache');
console.log('PASS 4 adapter tests');
