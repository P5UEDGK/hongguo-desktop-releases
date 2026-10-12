import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
import {parseSeasonTitle, seasonSearchQueries, findOtherSeasons,findNextSeason} from '../src/season-search.mjs';
import test from 'node:test';

const title='谁说没灵根不能修仙的？之无灵证道';
assert.equal(parseSeasonTitle(title).base,title);
assert.equal(parseSeasonTitle(title+'第二季').base,title);
assert.deepEqual(seasonSearchQueries(title),[title,'谁说没灵根不能修仙的']);
const seed={seriesId:'8800000000000002001',title,tags:['漫剧'],actors:[]};
const second={...seed,seriesId:'8800000000000002002',title:'谁说没灵根不能修仙的？之重登仙途第二季'};
const calls=[];
const api={
  searchNovelfm:async(query,page,mode)=>{calls.push(query);return {source:'novelfm',page,mode,hasMore:false,items:query===title?[]:[second]};},
  resolveSeasonCandidates:async(seed,items)=>({items,verified:items.some(row=>row.seriesId===second.seriesId)})
};
const result=await findOtherSeasons(api,seed);
assert.deepEqual(result.items,[second]);
assert.deepEqual(calls,[title,title,'谁说没灵根不能修仙的','谁说没灵根不能修仙的']);
assert.equal(seed.title,title);
console.log('PASS original Chinese question mark and subtitle fallback');

function fixture(respond,verify=items=>({items,verified:items.length>0})) {
  const seen=[];
  return {seen,api:{
    searchNovelfm:async(query,page,mode)=>{seen.push([query,page,mode]);return {source:'novelfm',page,mode,hasMore:false,items:[],...await respond(query,page,mode)};},
    resolveSeasonCandidates:async(seed,items)=>verify(items),
    validationEpisodes:async sid=>({seriesId:sid,title:second.title,total:100,episodes:[1]})
  }};
}
test('original punctuation, spaces and fullwidth season numbers are preserved in base',()=>{
  assert.equal(parseSeasonTitle(title+'第２季').base,title);
  assert.equal(parseSeasonTitle(title+'第２季').season,2);
  assert.equal(parseSeasonTitle('剧名：副题 第二季').base,'剧名：副题');
  assert.equal(parseSeasonTitle(null),null);
});
test('only question/exclamation/colon delimit fallback; no empty or one-character prefix',()=>{
  for(const mark of ['？','?','！','!',':','：'])assert.deepEqual(seasonSearchQueries('主标题'+mark+'副标题'),['主标题'+mark+'副标题','主标题']);
  for(const name of ['无符号','问？副题','？副题','主标题·副标题','主标题，副标题'])assert.deepEqual(seasonSearchQueries(name),[name]);
});
test('verified full query stops prefix fallback even with different subtitle',async()=>{
  const f=fixture(()=>({items:[second]}));const result=await findOtherSeasons(f.api,seed);
  assert.deepEqual(result.items,[second]);assert.equal(result.incomplete,false);
  assert.deepEqual(f.seen.map(row=>row[0]),[title,title]);
});
test('nonempty original response with conflicting album still falls back',async()=>{
  const foreign={...second,seriesId:'8800000000000002099'};
  const f=fixture(query=>({items:query===title?[foreign]:[second]}),items=>({items:items.filter(row=>row!==foreign),verified:items.includes(second)}));
  const result=await findOtherSeasons(f.api,seed);assert.deepEqual(result.items,[second]);assert.equal(f.seen.length,4);
});
test('unknown relation stays a manual candidate and does not stop fallback',async()=>{
  const f=fixture(()=>({items:[second]}),items=>({items,verified:false}));
  const result=await findOtherSeasons(f.api,seed);assert.deepEqual(result.items,[second]);assert.equal(result.automatic,false);assert.equal(f.seen.length,4);
});
test('unrelated prefixes and other media kinds never enter relation verification',async()=>{
  const other={...second,title:'谁说没灵根不能修仙的坏人？第二季'};
  const live={...second,seriesId:'8800000000000002098',tags:['真人']};
  const f=fixture(()=>({items:[other,live]}));assert.deepEqual((await findOtherSeasons(f.api,seed)).items,[]);
});
test('page signatures are scoped to query and mode, final candidates deduplicated',async()=>{
  const f=fixture((query,page)=>({items:query===title?[]:[second],hasMore:query!==title&&page===1}));
  const result=await findOtherSeasons(f.api,seed);assert.deepEqual(result.items,[second]);assert.equal(result.incomplete,true);
  assert.equal(new Set(f.seen.map(JSON.stringify)).size,f.seen.length);
});
test('failed or malformed primary response cannot trigger broader fallback',async()=>{
  for(const respond of [()=>{throw Error('network');},()=>({source:'wrong'})]){
    const f=fixture(respond);const result=await findOtherSeasons(f.api,seed);assert.equal(result.incomplete,true);assert.equal(f.seen.length,1);
  }
});
test('cancellation after a search prevents verification and fallback',async()=>{
  let live=true,verified=0;const f=fixture(()=>{live=false;return {items:[second]};},items=>{verified++;return {items,verified:true};});
  const result=await findOtherSeasons(f.api,seed,()=>live);assert.deepEqual(result.items,[]);assert.equal(f.seen.length,1);assert.equal(verified,0);
});
test('expired total budget starts no request and returns incomplete',async()=>{
  const f=fixture(()=>({}));const result=await findOtherSeasons(f.api,seed,()=>true,{deadline:Date.now()-1});assert.equal(result.incomplete,true);assert.equal(f.seen.length,0);
});
test('next season shares subtitle recovery but never auto-plays broad matches',async()=>{
  const f=fixture(query=>({items:query==='谁说没灵根不能修仙的'?[second]:[]}));
  const result=await findNextSeason(f.api,{...seed,title:title+'第一季'});assert.equal(result.items[0].seriesId,second.seriesId);assert.equal(result.automatic,false);assert.equal(result.incomplete,false);
  assert.ok(f.seen.every(row=>!row[0].includes('?')));assert.equal(new Set(f.seen.map(JSON.stringify)).size,f.seen.length);
});
test('verified exact next season retains strict automatic continuation',async()=>{
  const exact={...second,title:title+'第二季'};const f=fixture(()=>({items:[exact]}));f.api.validationEpisodes=async sid=>({seriesId:sid,title:exact.title,total:100,episodes:[1]});
  const result=await findNextSeason(f.api,{...seed,title:title+'第一季'});assert.equal(result.items.length,1);assert.equal(result.automatic,true);assert.equal(f.seen.length,4);
});
test('next season relation failure reports incomplete and never auto-plays',async()=>{
  const f=fixture(()=>({items:[]}));f.api.resolveSeasonCandidates=async()=>{throw Error('relations unavailable');};
  const result=await findNextSeason(f.api,{...seed,title:title+'第一季'});assert.equal(result.incomplete,true);assert.equal(result.automatic,false);
});
test('incomplete next-season pages do not start broader title queries',async()=>{
  const f=fixture(()=>({items:[],hasMore:true}));
  const result=await findNextSeason(f.api,{...seed,title:title+'第一季'});
  assert.equal(result.incomplete,true);assert.equal(result.automatic,false);
  assert.ok(f.seen.every(row=>row[0].endsWith('第二季')||row[0].endsWith('第2季')));
});

const realPages=JSON.parse(readFileSync(new URL('./fixtures/wuling-season-pages.json',import.meta.url),'utf8'));
const realRows=realPages.flatMap(page=>page.items||[]);
const realSeed=realRows.find(row=>row.title.endsWith('第33季'));
test('real 40-row response keeps all other seasons after page three fails',async()=>{
  const f=fixture((query,page)=>{
    const response=realPages[page-1];
    if(response.error)throw Error(response.error);
    return response;
  });
  const result=await findOtherSeasons(f.api,realSeed);
  assert.equal(result.items.length,39);
  assert.equal(new Set([realSeed,...result.items].map(row=>row.seriesId)).size,40);
  assert.equal(result.incomplete,true);
  assert.deepEqual(f.seen.map(row=>row[1]),[1,2,3]);
  assert.equal(parseSeasonTitle(result.items.at(-1).title).season,41);
  assert.equal(parseSeasonTitle(title+'４０季').base,title);
  assert.equal(parseSeasonTitle(title+'４０季').season,40);
});
test('spent search budget retains the fetched page without starting relation or more searches',async t=>{
  let now=1000,verified=0;
  t.mock.method(Date,'now',()=>now);
  const f=fixture(()=>{now=2001;return realPages[0];},items=>{verified++;return {items,verified:true};});
  const result=await findOtherSeasons(f.api,realSeed,()=>true,{deadline:2000});
  assert.equal(result.items.length,realPages[0].items.filter(row=>row.seriesId!==realSeed.seriesId).length);assert.equal(result.incomplete,true);assert.equal(result.automatic,false);
  assert.equal(f.seen.length,1);assert.equal(verified,0);
});
test('relation failure retains fetched candidates for final collect verification',async()=>{
  const f=fixture((query,page)=>{const response=realPages[page-1];if(response.error)throw Error(response.error);return response;});
  f.api.resolveSeasonCandidates=async()=>{throw Error('relation lookup timed out');};
  const result=await findOtherSeasons(f.api,realSeed);
  assert.equal(result.items.length,39);assert.equal(result.incomplete,true);assert.equal(result.automatic,false);
});
