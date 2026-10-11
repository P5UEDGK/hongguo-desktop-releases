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
// Reopening page one joins a later in-flight cursor and receives merged rows.
const reopenPending=createStore(endpoint);
const firstPage=reopenPending.read('comments',{kind:'episode'});pending.shift().resolve(page(['one'],'p2',true));await firstPage;
const nextPage=reopenPending.read('comments',{kind:'episode',cursor:'p2'});
const reopenedPage=reopenPending.read('comments',{kind:'episode'});
pending.shift().resolve(page(['two']));await nextPage;
assert.deepEqual((await reopenedPage).items.map(x=>x.id),['one','two'],'reopened cached page joins pending pagination');
reopenPending.dispose();
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
// Reopening before the later page finishes must wait and then fetch page one.
const inflight=createStore(endpoint);
const laterPending=inflight.read('comments',{kind:'episode',cursor:'p2'});
const firstPending=inflight.read('comments',{kind:'episode'});
assert.notEqual(firstPending,laterPending,'different cursors cannot share a result');
const beforeFirst=calls.length;
pending.shift().resolve(page(['second']));await laterPending;
await new Promise(setImmediate);
assert.equal(calls.length,beforeFirst+1,'page one runs after the different pending cursor');
assert.equal(calls.at(-1).url.searchParams.get('cursor'),null);
pending.shift().resolve(page(['first'],'p2',true));
assert.deepEqual((await firstPending).items.map(x=>x.id),['first']);
const beforeReload=calls.length, reloadSecond=inflight.read('comments',{kind:'episode',cursor:'p2'});
assert.equal(calls.length,beforeReload+1,'replaced page one invalidates later cursor markers');
pending.shift().resolve(page(['second']));
assert.deepEqual((await reloadSecond).items.map(x=>x.id),['first','second']);
const third=inflight.read('comments',{kind:'series',cursor:'later'});
const queued=inflight.read('comments',{kind:'series'});
inflight.dispose();await assert.rejects(third,{name:'AbortError'});await assert.rejects(queued,{name:'AbortError'});
pending.shift();
// Waiting on another cursor consumes the same read's 15-second budget.
const realNow=Date.now,realTimer=setTimeout,realClear=clearTimeout;
let now=0,token=0;const timers=new Map();
Date.now=()=>now;globalThis.setTimeout=(fn,ms)=>{timers.set(++token,{fn,due:now+ms,ms});return token;};
globalThis.clearTimeout=id=>timers.delete(id);
const slow=createStore(endpoint);
try{
  const late=slow.read('comments',{kind:'episode',cursor:'later'});now=1000;
  const queued=slow.read('comments',{kind:'episode'});now=14000;
  pending.shift().resolve(page(['later']));await late;await new Promise(setImmediate);
  assert([...timers.values()].every(t=>t.due<=16000),'queued page one must not receive a second 15-second deadline');
  now=16000;for(const [id,timer] of [...timers])if(timer.due<=now){timers.delete(id);timer.fn();}
  await assert.rejects(queued,error=>['AbortError','TimeoutError'].includes(error.name));pending.shift();
}finally{slow.dispose();Date.now=realNow;globalThis.setTimeout=realTimer;globalThis.clearTimeout=realClear;}
// A prior cursor timing out cannot spend a later read's remaining budget.
now=0;timers.clear();Date.now=()=>now;
globalThis.setTimeout=(fn,ms)=>{timers.set(++token,{fn,due:now+ms,ms});return token;};
globalThis.clearTimeout=id=>timers.delete(id);
const timedOutCursor=createStore(endpoint);
try{
  const late=timedOutCursor.read('comments',{kind:'episode',cursor:'late'});
  const rejected=assert.rejects(late,{name:'AbortError'});pending.shift();now=14000;
  const queued=timedOutCursor.read('comments',{kind:'episode'});
  const count=calls.length;now=15000;
  for(const [id,timer] of [...timers])if(timer.due<=now){timers.delete(id);timer.fn();}
  await rejected;await new Promise(setImmediate);
  assert.equal(calls.length,count+1,'page one must use a fresh controller after old cursor timeout');
  assert.equal(calls.at(-1).url.searchParams.get('cursor'),null);
  assert(!calls.at(-1).options.signal.aborted);
  pending.shift().resolve(page(['reopened']));
  assert.deepEqual((await queued).items.map(x=>x.id),['reopened']);
}finally{timedOutCursor.dispose();Date.now=realNow;globalThis.setTimeout=realTimer;globalThis.clearTimeout=realClear;}
console.log('PASS session cache, in-flight reuse, pagination, tab/reply isolation, refresh, failure retry and disposal');

// Request-page reads share transport with merged readers without losing provenance.
const rawStore=createStore(endpoint);
const rawFirst=rawStore.readPage('replies',{comment_id:'raw'});
pending.shift().resolve(page(['one'],'p2',true));await rawFirst;
const mergedSecond=rawStore.read('replies',{comment_id:'raw',cursor:'p2'});
const rawSecond=rawStore.readPage('replies',{comment_id:'raw',cursor:'p2'});
pending.shift().resolve(page(['two']));
assert.deepEqual((await mergedSecond).items.map(x=>x.id),['one','two']);
assert.deepEqual((await rawSecond).items.map(x=>x.id),['two']);
assert.deepEqual((await rawStore.readPage('replies',{comment_id:'raw'})).items.map(x=>x.id),['one']);
assert.deepEqual((await rawStore.readPage('replies',{comment_id:'raw',cursor:'p2'})).items.map(x=>x.id),['two']);
rawStore.dispose();
console.log('PASS requested-page cache retains raw pagination provenance');
