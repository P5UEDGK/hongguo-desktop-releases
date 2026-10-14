import assert from 'node:assert/strict';
import {createLibraryUI} from '../src/frontend-library.mjs';
import {findOtherSeasons} from '../src/season-search.mjs';

globalThis.window=new EventTarget();
globalThis.document={createElement:()=>({}),head:{append:()=>{}}};
const title='谁说没灵根不能修仙的？之无灵证道';
const seed={seriesId:'8800000000000002001',title,tags:['漫剧'],actors:[]};
const related={...seed,seriesId:'8800000000000002002',title:'谁说没灵根不能修仙的？之再问长生第二季'};
const conflict={...related,seriesId:'8800000000000002099'};
const unknown={...related,seriesId:'8800000000000002098'};
const rows=[seed,related,conflict,unknown],native=new Map([[seed.seriesId,seed]]),seen=[];
let active=0,peak=0,detailPosts=0;
const api={
  validationStatus:async()=>({baseUrl:'http://127.0.0.1:12345'}),
  favorites:async()=>[...native.values()],history:async()=>[],
  setFavorite:async(item,value)=>value?native.set(item.seriesId,item):native.delete(item.seriesId),
  searchNovelfm:async(query,page,mode)=>{
    active++;peak=Math.max(peak,active);seen.push(query);
    await new Promise(done=>setImmediate(done));active--;
    return {source:'novelfm',page,mode,hasMore:false,items:query===title?[conflict]:[related,conflict,unknown]};
  }
};
globalThis.fetch=async(url,options)=>{
  if(options.method!=='GET')detailPosts++;
  return {ok:true,json:async()=>({requestToken:'fixture',manual:{},relations:rows.map((row,index)=>({seriesId:row.seriesId,albumId:index===2?'7619198149772446783':index===3?null:'7619198149772446782',season:index+1,retryAt:index===3?Date.now()+86400000:0}))})};
};
const ui=createLibraryUI({React:{},jsxRuntime:{},api,Cover:()=>null,coverFallback:'fixture'});
await api.favorites();await ui.library.load();
const collect=()=>ui.library.collect(seed,()=>ui.seasonSearch(api,seed,()=>true,findOtherSeasons,'fixture'),()=>true,()=>{});
const result=await collect();await ui.library.syncAutoFavorites();
assert.deepEqual([...native.keys()].sort(),[seed.seriesId,related.seriesId]);
assert.equal(result.added,1);assert.deepEqual(result.uncertain,[unknown]);
assert.deepEqual(seen,[title,title,'谁说没灵根不能修仙的','谁说没灵根不能修仙的']);
assert.equal(native.get(seed.seriesId).title,title);assert.equal(native.get(related.seriesId).title,related.title);
assert.equal(detailPosts,0);assert.equal(peak,1);
console.log('PASS default finder/proxy keeps Chinese punctuation, verifies conflicting original results, saves only same album and retains unknown for manual selection');
const again=await collect();assert.equal(again.added,0);assert.equal(native.size,2);assert.equal(detailPosts,0);
console.log('PASS repeat collection reuses relationships and never duplicates native membership');
