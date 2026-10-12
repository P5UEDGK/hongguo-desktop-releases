const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../src/library-core.mjs'),'utf8').split('export {')[0];
const turn=()=>new Promise(resolve=>setImmediate(resolve));
const defer=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject};};
const context=vm.createContext({URL,AbortController,setTimeout,clearTimeout,queueMicrotask,Date,console});
vm.runInContext(source,context);
const Queue=vm.runInContext('DesktopSearchQueue',context),create=vm.runInContext('desktopCreateLibrary',context),groups=vm.runInContext('desktopLibraryGroups',context);
const page=vm.runInContext('desktopLibraryPage',context),progress=vm.runInContext('desktopLibraryProgress',context);
const SID='7673807696302197784',OTHER='7677914379060251673',THIRD='7681903520873729048',FOREIGN='99990004',UNKNOWN='99990005',ALBUM='7619198149772446782';
const item=sid=>({seriesId:sid,title:'测试第九季',tags:['漫剧'],actors:[],episodeCount:9});
function fixture(){
  const values=new Map(),favoriteIds=new Set(),calls=[],events=[];let blocker=null;
  const records=[SID,OTHER,THIRD,FOREIGN,UNKNOWN].map((sid,index)=>({seriesId:sid,albumId:sid===UNKNOWN?null:sid===FOREIGN?'99990009':ALBUM,season:index+1,title:'测试',state:'resolved',retryAt:0}));
  context.fetch=async(url,options)=>{
    calls.push({url,options});if(options.method==='GET')return {ok:true,json:async()=>({relations:[...values.values()],manual:{},requestToken:'session'})};
    if(blocker)await blocker.promise;
    const ids=JSON.parse(options.body).seriesIds;
    const rows=records.filter(row=>ids.includes(row.seriesId));rows.forEach(row=>values.set(row.seriesId,row));
    return {ok:true,json:async()=>({relations:rows})};
  };
  const api={validationStatus:async()=>({baseUrl:'http://127.0.0.1:12345'}),
    setFavorite:async(row,value)=>{events.push([row.seriesId,value]);value?favoriteIds.add(row.seriesId):favoriteIds.delete(row.seriesId);},
    favorites:async()=>[...favoriteIds].map(item),history:async()=>[]};
  return {api,values,favoriteIds,calls,events,set blocker(value){blocker=value;},store:create(api,()=>{})};
}
(async()=>{
  let count=0;
  async function test(name,work){await work();count++;console.log('PASS',name);}
  await test('pagination handles many seasons, shrink, zero and invalid page',async()=>{
    const rows=Array.from({length:25},(_,i)=>i);
    assert.equal(page(rows,1,12).items.length,12);assert.equal(page(rows,3,12).items[0],24);
    assert.equal(page(rows,99,12).page,3);assert.equal(page([],2,12).page,1);
    assert.equal(page(rows,NaN,12).page,1);assert.equal(page(rows,-5,12).page,1);
    assert.equal(page(rows.slice(0,12),3,12).page,1);assert.equal(page(rows,2,8).items[0],8);
  });
  await test('watch percent uses latest episode, not maximum or aggregate',async()=>{
    const a={...item(SID),episodeCount:100},b={...item(OTHER),episodeCount:20};
    const history=[{...a,lastEpisode:99,updatedAt:1},{...b,lastEpisode:10,updatedAt:2}];
    const value=progress([a,b],history,new Map([[OTHER,{season:10}]]));
    assert.equal(value.percent,50);assert.equal(value.seriesId,OTHER);assert.equal(value.label,'第 10 季 · 已看 50%');
    assert.equal(progress([a],[{...a,lastEpisode:50}]).label,'已看 50%');
    assert.equal(progress([a],[{...a,lastEpisode:1}]).percent,1);
  });
  await test('watch progress handles absent history, unknown totals and bounds',async()=>{
    const a={...item(SID),episodeCount:100};assert.equal(progress([a],[]).label,'未观看');
    assert.equal(progress([a],[{...a,lastEpisode:500}]).percent,100);
    assert.equal(progress([{...a,episodeCount:0}],[{...a,episodeCount:0,lastEpisode:50}]).label,'看到第 50 集');
    assert.equal(progress([a],[{...a,lastEpisode:NaN}]).percent,null);
    assert.equal(progress([a],[{...a,lastEpisode:0}]).seriesId,null);
    assert.equal(progress([a],[{...a,lastEpisode:99,updatedAt:1},{...a,lastEpisode:20,updatedAt:2}]).percent,20);
  });
  await test('single search, duplicate promise, cancellation retains native slot',async()=>{
    const queue=new Queue(),block=defer(),seen=[];
    const first=queue.run('a','a',context=>context.request(()=>{seen.push('a');return block.promise;}));
    const caught=first.catch(error=>error.message);
    assert.equal(first,queue.run('a','duplicate',()=>{throw Error('duplicate');}));
    await turn();queue.cancel();
    const second=queue.run('b','b',context=>context.request(()=>{seen.push('b');return 2;}));
    await turn();assert.deepEqual(seen,['a']);assert.equal(queue.state().cancelled,true);
    block.resolve(1);assert.equal(await caught,'搜索已取消');assert.equal(await second,2);assert.deepEqual(seen,['a','b']);
  });
  await test('timed-out task holds slot until underlying request completes',async()=>{
    const queue=new Queue(),block=defer(),seen=[];
    const first=queue.run('race','race',context=>{context.request(()=>block.promise);return 'timed out';});
    const caught=first.catch(error=>error.message);await turn();queue.cancel();
    const second=queue.run('later','later',()=>seen.push('later'));
    await turn();assert.equal(seen.length,0);block.resolve();assert.equal(await caught,'搜索已取消');await second;
  });
  await test('parallel search calls have execution peak one',async()=>{
    const queue=new Queue();let active=0,peak=0;
    await Promise.all(Array.from({length:10},(_,index)=>queue.run(String(index),'search',context=>context.request(async()=>{
      peak=Math.max(peak,++active);await turn();active--;return index;
    }))));assert.equal(peak,1);
  });
  await test('favorite saved before delayed metadata; overlapping lookups coalesced',async()=>{
    const f=fixture(),block=defer();f.blocker=block;
    await f.store.favorite(item(SID),true);assert.equal(f.favoriteIds.has(SID),true);
    const a=f.store.ensure([item(SID)]),b=f.store.ensure([item(SID)]);await turn();
    assert.equal(f.calls.filter(call=>call.options.method==='POST').length,1);
    block.resolve();await Promise.all([a,b]);
    await f.store.favorite(item(SID),false);await f.store.favorite(item(SID),true);await turn();
    assert.equal(f.calls.filter(call=>call.options.method==='POST').length,1);
    assert.equal(f.store.relations.get(SID).albumId,ALBUM);
  });
  await test('restart loads persisted relation without upstream detail',async()=>{
    const f=fixture();await f.store.ensure([item(SID)]);const before=f.calls.filter(call=>call.options.method==='POST').length;
    const restart=create(f.api,()=>{});await restart.ensure([item(SID)]);
    assert.equal(f.calls.filter(call=>call.options.method==='POST').length,before);
  });
  await test('manual grouping targets contain saved library members only',async()=>{
    const f=fixture();await f.store.ensure([item(FOREIGN)]);assert.equal(f.store.known.size,0);
    await f.store.observe([item(SID)],'favorites');await f.store.observe([item(OTHER)],'history');
    assert.equal(f.store.known.size,2);await f.store.favorite(item(SID),false);
    assert.equal(f.store.known.has(SID),false);assert.equal(f.store.known.has(OTHER),true);
  });
  await test('grouping preserves page membership, season order and unknown singleton',async()=>{
    const f=fixture();await f.store.ensure([SID,OTHER,UNKNOWN]);
    let value=groups([item(OTHER),item(SID),item(UNKNOWN)],f.store.relations,new Map());
    assert.equal(value.length,2);assert.equal(value[0].items[0].seriesId,SID);
    value=groups([item(OTHER)],f.store.relations,new Map());assert.equal(value[0].items.length,1);
    value=groups([item(SID),item(UNKNOWN)],f.store.relations,new Map([[UNKNOWN,'album:'+ALBUM]]));assert.equal(value.length,1);
  });
  await test('collect only verified album, skips existing; unknown needs selection',async()=>{
    const f=fixture();f.favoriteIds.add(SID);
    const result=await f.store.collect(item(SID),async()=>({items:[item(OTHER),item(OTHER),item(FOREIGN),item(UNKNOWN)],incomplete:true}),()=>true,()=>{});
    assert.equal(result.added,1);assert.equal(result.skipped,1);assert.equal(result.uncertain.length,1);
    assert.equal(result.uncertain[0].seriesId,UNKNOWN);assert.equal(f.favoriteIds.has(FOREIGN),false);assert.equal(result.incomplete,true);
  });
  await test('remove during search is not resurrected by late collect',async()=>{
    const f=fixture(),block=defer();
    const task=f.store.collect(item(SID),()=>block.promise,()=>true,()=>{});
    await f.store.favorite(item(OTHER),false);
    block.resolve({items:[item(OTHER)],incomplete:false});
    await task;assert.equal(f.favoriteIds.has(OTHER),false);
  });
  await test('cancel during metadata prevents any batch favorite writes',async()=>{
    const f=fixture(),block=defer();let live=true;f.blocker=block;
    const task=f.store.collect(item(SID),async()=>({items:[item(OTHER)],incomplete:false}),()=>live,()=>{}).catch(error=>error.message);
    await turn();live=false;block.resolve();assert.equal(await task,'搜索已取消');assert.equal(f.events.length,0);
  });
  await test('per-series writes preserve quick remove and re-add ordering',async()=>{
    const f=fixture();await Promise.all([f.store.favorite(item(SID),true),f.store.favorite(item(SID),false),f.store.favorite(item(SID),true)]);
    assert.equal(f.favoriteIds.has(SID),true);assert.deepEqual(f.events.map(row=>row[1]),[true,false,true]);await turn();
  });
  console.log('PASS',count,'library tests');
})().catch(error=>{console.error(error);process.exitCode=1;});
