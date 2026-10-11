import assert from 'node:assert/strict';
import {createComments} from '../src/comments.mjs';
const {createStore}=createComments({React:{},jsxRuntime:{},resolveEndpoint(){},installStyles(){},danmaku:{},emojis:{}});
const endpoint={origin:'http://127.0.0.1:1234',key:'fixture-only',series:'10000000000000001',episode:'1'};
let calls=[],pending=[];
globalThis.fetch=(url,options)=>new Promise((resolve,reject)=>{
  const row={url:new URL(url),options,resolve:result=>resolve({ok:true,json:async()=>result}),fail:()=>reject(Error('offline'))};
  calls.push(row);pending.push(row);options.signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')),{once:true});
});
const page=(ids,cursor='',more=false)=>({items:ids.map(id=>({id})),cursor,has_more:more,total:2});
const store=createStore(endpoint);
const first=store.read('comments',{kind:'episode',cursor:''}), duplicate=store.read('comments',{kind:'episode',cursor:''});
assert.equal(first,duplicate);assert.equal(calls.length,1);
pending.shift().resolve(page(['1'],'opaque:+/==',true));await first;
assert.deepEqual(await store.read('comments',{kind:'episode'}),await first);assert.equal(calls.length,1);
const next=store.read('comments',{kind:'episode',cursor:'opaque:+/=='});pending.shift().resolve(page(['1','2']));await next;
assert.deepEqual((await store.read('comments',{kind:'episode'})).items.map(x=>x.id),['1','2']);assert.equal(calls.length,2);
const series=store.read('comments',{kind:'series'});pending.shift().resolve(page(['series']));await series;assert.equal(calls.length,3);
const reply=store.read('replies',{comment_id:'1'}),again=store.read('replies',{comment_id:'1'});assert.equal(reply,again);pending.shift().resolve(page(['reply']));await reply;
await store.read('replies',{comment_id:'1'});assert.equal(calls.length,4);
store.clear('comments',{kind:'episode'});
const refresh=store.read('comments',{kind:'episode'});pending.shift().resolve(page(['fresh']));await refresh;assert.equal(calls.length,5);
assert.equal((await store.read('comments',{kind:'series'})).items[0].id,'series');assert.equal(calls.length,5);
const failure=store.read('metrics');pending.shift().fail();await assert.rejects(failure,/offline/);
const retry=store.read('metrics');pending.shift().resolve({likes:4});await retry;assert.equal(calls.length,7);
const old=store.read('replies',{comment_id:'pending'});store.dispose();await assert.rejects(old,{name:'AbortError'});pending.shift();
const clean=store.read('comments',{kind:'episode'});pending.shift().resolve(page(['new-session']));await clean;assert.equal(calls.length,9);
store.dispose();
// A late pagination request can recreate an evicted entry without page one.
const evicted=createStore(endpoint);
const initial=evicted.read('comments',{kind:'episode'});pending.shift().resolve(page(['first'],'p2',true));await initial;
for(let i=0;i<32;i++){
  const reply=evicted.read('replies',{comment_id:String(i)});pending.shift().resolve(page(['reply']));await reply;
}
const later=evicted.read('comments',{kind:'episode',cursor:'p2'});pending.shift().resolve(page(['second']));await later;
const count=calls.length,reopen=evicted.read('comments',{kind:'episode'});
assert.equal(calls.length,count+1,'reopening an entry with only later pages must fetch page one');
assert.equal(calls.at(-1).url.searchParams.get('cursor'),null);
pending.shift().resolve(page(['first'],'p2',true));assert.deepEqual((await reopen).items.map(x=>x.id),['first']);
evicted.dispose();
console.log('PASS session cache, in-flight reuse, pagination, tab/reply isolation, refresh, failure retry and disposal');
