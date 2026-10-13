import assert from 'node:assert/strict';
import test from 'node:test';
import {DesktopSearchQueue,desktopLibraryNext} from '../src/library-core.mjs';
import {createLibraryUI} from '../src/frontend-library.mjs';
import {findNextSeason} from '../src/season-search.mjs';
import {createSeasonPlayback} from '../src/season-playback.mjs';

const turn=()=>new Promise(done=>setImmediate(done));
const settle=async()=>{for(let i=0;i<40;i++)await turn();};
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const ids=['8800000000000002001','8800000000000002002','8800000000000002003','8800000000000002099','8800000000000002098'];
const album='7619198149772446782';
const rows=ids.map((seriesId,index)=>({seriesId,title:'验收作品第'+(index+1)+'季',tags:['漫剧'],actors:[],cover:'',intro:'',episodeCount:2,webAccessibleEpisodes:0}));
function fixture(storage=new Map()) {
  globalThis.window=new EventTarget();
  globalThis.document={createElement:()=>({}),head:{append(){}}};
  globalThis.localStorage={getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)};
  const native=new Map(),metadata=new Map(),calls=[];
  let gate=null,failure=false,writeFail=null;
  const relations=rows.map((row,index)=>({seriesId:row.seriesId,albumId:index===3?'7619198149772446799':index===4?null:album,season:index+1,state:'resolved',retryAt:0,title:row.title}));
  globalThis.fetch=async(url,options)=>({ok:true,json:async()=>{
    if(options.method==='GET')return {relations:[...metadata.values()],requestToken:'fixture',manual:{}};
    const requested=JSON.parse(options.body).seriesIds;
    const found=relations.filter(row=>requested.includes(row.seriesId));found.forEach(row=>metadata.set(row.seriesId,row));
    return {relations:found};
  }});
  const api={
    validationStatus:async()=>({baseUrl:'http://127.0.0.1:12345'}),
    favorites:async()=>[...native.values()],history:async()=>[],
    setFavorite:async(item,value)=>{
      calls.push(['save',item.seriesId,value]);
      if(writeFail===item.seriesId&&value)throw Error('write failed');
      value?native.set(item.seriesId,item):native.delete(item.seriesId);
    },
    search:async()=>{calls.push(['manual']);return [];},
    searchNovelfm:async(query,page,mode)=>{
      calls.push(['search',query,page,mode]);if(gate)await gate.promise;if(failure)throw Error('upstream failed');
      return {source:'novelfm',page,mode,hasMore:false,items:rows.slice(1)};
    },
    validationEpisodes:async seriesId=>({seriesId,total:2,episodes:[1,2]})
  };
  const ui=createLibraryUI({React:{},jsxRuntime:{},api,Cover:()=>null,coverFallback:''});
  return {api,ui,native,metadata,calls,storage,set gate(value){gate=value;},set failure(value){failure=value;},set writeFail(value){writeFail=value;}};
}
test('background saves seed first, verifies same album, excludes unknown/conflict and does not recurse',async()=>{
  const f=fixture(),gate=deferred();f.gate=gate;
  await f.api.setFavorite(rows[0],true);
  assert.equal(f.native.has(ids[0]),true);assert.deepEqual(f.calls[0],['save',ids[0],true]);
  await settle();assert(f.calls.some(row=>row[0]==='search'));
  assert.equal(f.native.size,1);
  gate.resolve();await settle();await f.ui.library.syncAutoFavorites();
  assert.deepEqual([...f.native.keys()].sort(),ids.slice(0,3));
  const searches=f.calls.filter(row=>row[0]==='search').length;
  assert.equal(searches,2);await settle();assert.equal(f.calls.filter(row=>row[0]==='search').length,searches);
});
test('successful discovery survives a fresh UI and repeats do not search or overwrite excluded seasons',async()=>{
  const f=fixture();await f.api.setFavorite(rows[0],true);await settle();
  await f.api.setFavorite(rows[1],false);await settle();
  const next=fixture(f.storage);next.metadata.set(ids[0],f.metadata.get(ids[0]));
  await next.api.setFavorite(rows[0],true);await settle();
  assert.equal(next.calls.filter(row=>row[0]==='search').length,0);
  assert.equal(next.native.has(ids[2]),true);assert.equal(next.native.has(ids[1]),false);
});
test('cancelling seed during search prevents late candidates from being saved',async()=>{
  const f=fixture(),gate=deferred();f.gate=gate;
  await f.api.setFavorite(rows[0],true);await settle();
  await f.api.setFavorite(rows[0],false);gate.resolve();await settle();
  assert.equal(f.native.size,0);assert.equal(f.ui.library.discoveryRecord(rows[0]),undefined);
});
test('same album requests coalesce and a remaining user seed can complete after first seed cancellation',async()=>{
  const f=fixture(),gate=deferred();f.gate=gate;
  await f.api.setFavorite(rows[0],true);await settle();
  await f.api.setFavorite(rows[1],true);await settle();
  await f.api.setFavorite(rows[0],false);gate.resolve();await settle();
  assert.equal(f.native.has(ids[0]),false);assert.equal(f.native.has(ids[2]),true);
  assert.equal(f.calls.filter(row=>row[0]==='search').length,2);
});
test('manual 查找并收藏各季 and next-season lookup share the ongoing favorite search',async()=>{
  const f=fixture(),gate=deferred();f.gate=gate;
  await f.api.setFavorite(rows[0],true);await settle();
  const manual=f.ui.collectSeasons(rows[0],{progress:()=>{}});
  const next=f.ui.seasonSearch(f.api,rows[0],()=>true,findNextSeason,'查找下一季');
  await settle();gate.resolve();const [collected,season]=await Promise.all([manual,next]);await settle();
  assert.equal(collected.added,2);assert.equal(season.items[0].seriesId,ids[1]);assert.equal(season.automatic,true);
  assert.equal(f.calls.filter(row=>row[0]==='search').length,2);
});
test('next-season search alone reuses 查找各季 without collecting or writing history',async()=>{
  const f=fixture();
  const result=await f.ui.seasonSearch(f.api,rows[0],()=>true,findNextSeason,'查找下一季');await settle();
  assert.equal(result.automatic,true);assert.equal(result.items[0].seriesId,ids[1]);
  assert.equal(f.native.size,0);assert.equal(f.calls.filter(row=>row[0]==='save').length,0);
  assert.equal(f.calls.filter(row=>row[0]==='search').length,2);
});
test('failed search preserves favorite and persists bounded cooldown through restart',async()=>{
  const f=fixture();f.failure=true;
  await f.api.setFavorite(rows[0],true);await settle();assert(f.native.has(ids[0]));
  const record=f.ui.library.discoveryRecord(rows[0]);assert.equal(record.complete,false);assert(record.retryAt>Date.now());
  const next=fixture(f.storage);next.failure=true;
  await next.api.setFavorite(rows[0],true);await settle();
  assert.equal(next.calls.filter(row=>row[0]==='search').length,0);assert(next.native.has(ids[0]));
});
test('native candidate write failure retries on next trigger and never retracts seed',async()=>{
  const f=fixture();f.writeFail=ids[1];
  await f.api.setFavorite(rows[0],true);await settle();assert(f.native.has(ids[0]));assert(!f.native.has(ids[1]));
  f.writeFail=null;
  // The cooldown is event-triggered, never a periodic retry.
  const record=f.ui.library.discoveryRecord(rows[0]);record.retryAt=0;
  await f.api.setFavorite(rows[0],true);await settle();
  assert(f.native.has(ids[1]));
});
test('background yields between native calls to manual search while execution peak stays one',async()=>{
  const q=new DesktopSearchQueue(),gate=deferred(),trace=[];let active=0,peak=0;
  const request=async(label,promise)=>{active++;peak=Math.max(peak,active);trace.push(label);if(promise)await promise;active--;};
  const background=q.run('bg','background',async ctx=>{
    await ctx.request(()=>request('background-1',gate.promise));
    await ctx.request(()=>request('background-2'));
  },{background:true});
  await turn();
  const foreground=q.run('fg','manual',ctx=>ctx.request(()=>request('manual')));
  gate.resolve();await Promise.all([background,foreground]);
  assert.deepEqual(trace,['background-1','manual','background-2']);assert.equal(peak,1);
});
test('priority does not overlap a timed-out original background IPC and cancellation retires paused work',async()=>{
  const q=new DesktopSearchQueue(),gate=deferred(),trace=[];
  const background=q.run('bg','background',async ctx=>{
    await Promise.race([ctx.request(()=>gate.promise),Promise.resolve()]);
    await ctx.request(()=>{trace.push('late-background');});
  },{background:true}).catch(()=>{trace.push('cancelled');});
  await turn();
  const foreground=q.run('fg','manual',async ctx=>{trace.push('manual');q.cancel();});
  await turn();assert.deepEqual(trace,[]);
  gate.resolve();await Promise.allSettled([background,foreground]);
  assert.deepEqual(trace,['manual','cancelled']);
});
test('known next season uses authoritative season order with zero search including changed subtitle',async()=>{
  const f=fixture();
  f.native.set(ids[0],rows[0]);
  f.native.set(ids[1],{...rows[1],title:'验收作品：新副标题第二季'});
  await f.api.favorites();
  await f.ui.library.ensure(rows.slice(0,3));
  const value=await f.ui.seasonSearch(f.api,rows[0],()=>true,findNextSeason,'查找下一季');
  assert.equal(value.automatic,true);assert.equal(value.items[0].seriesId,ids[1]);
  assert.equal(f.calls.filter(row=>row[0]==='search').length,0);
  assert.equal(f.native.size,2);assert.equal(f.calls.filter(row=>row[0]==='save').length,0);
});
test('gap, unknown season, conflicting album and duplicate versions never become automatic',()=>{
  const relations=new Map([[ids[0],{albumId:album,season:1}],[ids[2],{albumId:album,season:3}]]);
  assert.equal(desktopLibraryNext(rows[0],[rows[2]],relations).items.length,0);
  relations.set(ids[1],{albumId:album,season:2});relations.set(ids[3],{albumId:album,season:2});
  assert.equal(desktopLibraryNext(rows[0],[rows[1],rows[3]],relations).automatic,false);
  assert.equal(desktopLibraryNext(rows[0],[rows[1]],relations).automatic,false,'a second known relationship is ambiguous even if its card is not loaded');
  relations.set(ids[1],{albumId:'7619198149772446799',season:2});
  assert.equal(desktopLibraryNext(rows[0],[rows[1]],relations).items.length,0);
});
class Media extends EventTarget {
  constructor(){super();Object.assign(this,{paused:false,seeking:false,ended:false,currentTime:0,duration:100,playbackRate:1});}
}
function playbackFixture({lookup=async()=>({items:[rows[1]],automatic:true,incomplete:false}),resolver}={}) {
  const media=new Media(),calls=[];let released=0,healthy=true;
  const initial={seriesId:ids[0],episode:1,total:3,source:'authorizedLocalApi',streamFormat:'hls',streamUrl:'http://fixture/current'};
  const next={...initial,seriesId:ids[1],episode:1,total:2,streamUrl:'http://fixture/next'};
  const controller=createSeasonPlayback({
    find:async(...args)=>{calls.push('find');return lookup(...args);},
    resolve:async(...args)=>{calls.push('resolve');return resolver?resolver(...args):next;},
    prepare:()=>{calls.push('prepare');return {dispose(){released++;}};},
    shouldPrewarm:media=>(media.duration-media.currentTime)/media.playbackRate<=12
  });
  const attach=episode=>controller.attach({series:rows[0],session:{...initial,episode},media,enabled:true,healthy:()=>healthy});
  return {controller,media,calls,attach,next,get released(){return released;},set healthy(v){healthy=v;}};
}
test('penultimate finds metadata, last resolves first source, near end warms only once and take transfers ownership',async()=>{
  const f=playbackFixture();let stop=f.attach(2);await settle();
  assert.deepEqual(f.calls,['find']);stop();stop=f.attach(3);await settle();
  assert.deepEqual(f.calls,['find','resolve']);
  f.media.currentTime=89;f.media.dispatchEvent(new Event('timeupdate'));await settle();
  f.media.dispatchEvent(new Event('timeupdate'));await settle();assert.deepEqual(f.calls,['find','resolve','prepare']);
  const taken=f.controller.take(rows[1]);assert.equal(taken.session,f.next);stop();assert.equal(f.released,0);
  taken.preparation.dispose();assert.equal(f.released,1);
});
test('in-flight metadata survives ordinary penultimate to last transition without duplicate search',async()=>{
  const gate=deferred(),f=playbackFixture({lookup:()=>gate.promise});
  const stop=f.attach(2);await settle();stop();f.attach(3);await settle();
  gate.resolve({items:[rows[1]],automatic:true,incomplete:false});await settle();
  assert.deepEqual(f.calls,['find','resolve']);f.controller.cancel();
});
test('handoff snapshots controls before the retired HLS placeholder restores default values',async()=>{
  const media=new Media();Object.assign(media,{currentTime:95,playbackRate:2,volume:.35,muted:true});
  const next={seriesId:ids[1],episode:1,total:2,source:'authorizedLocalApi',streamFormat:'hls',streamUrl:'http://fixture/next'};
  const c=createSeasonPlayback({find:async()=>({items:[rows[1]],automatic:true}),resolve:async()=>next,shouldPrewarm:()=>true,
    prepare:()=>({dispose(){},async claimRecord(){return {settings:{rate:media.playbackRate},adopt(target){target.playbackRate=1;target.volume=1;target.muted=false;return 'adopted';}};}})});
  c.attach({series:rows[0],session:{seriesId:ids[0],episode:3,total:3,source:'authorizedLocalApi',streamFormat:'hls'},media,enabled:true,healthy:()=>true});
  await settle();const taken=c.take(rows[1]);media.playbackRate=1;media.volume=1;media.muted=false;
  const record=await taken.preparation.claimRecord();assert.deepEqual(record.settings,{rate:2,volume:.35,muted:true});
  const target={};assert.equal(record.adopt(target,{}),'adopted');assert.deepEqual(target,{playbackRate:2,volume:.35,muted:true});c.cancel();
});
test('disabled continuation, pause, buffering and wrong source never prewarm',async()=>{
  const f=playbackFixture();f.media.paused=true;const stop=f.attach(3);await settle();
  assert.deepEqual(f.calls,['find']);
  f.media.paused=false;f.healthy=false;f.media.currentTime=95;f.media.dispatchEvent(new Event('timeupdate'));await settle();
  assert(!f.calls.includes('resolve'));stop();
  const g=playbackFixture({resolver:async()=>({seriesId:ids[2],episode:1,total:2,source:'authorizedLocalApi',streamUrl:'wrong'})});
  g.attach(3);await settle();g.media.currentTime=95;g.media.dispatchEvent(new Event('timeupdate'));await settle();
  assert(!g.calls.includes('prepare'));g.controller.cancel();
});
test('late lookup/source after changing episode or closing is discarded; standby is disposed on cancel',async()=>{
  const gate=deferred(),f=playbackFixture({resolver:()=>gate.promise});const stop=f.attach(3);await settle();
  stop();gate.resolve(f.next);await settle();assert.equal(f.controller.take(rows[1]),null);assert(!f.calls.includes('prepare'));
  const g=playbackFixture();g.media.currentTime=95;g.attach(3);await settle();assert(g.calls.includes('prepare'));
  g.controller.cancel();assert.equal(g.released,1);assert.equal(g.controller.take(rows[1]),null);
});
test('2x playback triggers at twelve seconds of real remaining time, and incomplete lookup does not load video',async()=>{
  const f=playbackFixture();f.media.playbackRate=2;f.media.currentTime=77;f.attach(3);await settle();
  assert(f.calls.includes('prepare'));f.controller.cancel();
  const g=playbackFixture({lookup:async()=>({items:[rows[1]],automatic:false,incomplete:true})});
  g.media.currentTime=99;g.attach(3);await settle();assert.deepEqual(g.calls,['find']);g.controller.cancel();
});
