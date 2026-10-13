const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const CustomEvent = globalThis.CustomEvent || class extends Event {constructor(type,options){super(type);this.detail=options.detail;}};
const source = fs.readFileSync(path.join(__dirname,'../src/danmaku.mjs'),'utf8').replace('export function','function');
const frames = [], pending = [], events = new Map();
const layer = {children:[],setAttribute(){},append(node){this.children.push(node);node.remove=()=>this.children=this.children.filter(n=>n!==node)},replaceChildren(){this.children=[]},remove(){}};
const stage = {clientWidth:1000,classList:{contains:()=>false},append(){}};
const media = {currentTime:0,duration:192,clientWidth:1000,clientHeight:646,closest:()=>stage,dispatchEvent(){},
  addEventListener:(name,fn)=>events.set(name,fn),removeEventListener:name=>events.delete(name)};
const context = vm.createContext({URL,URLSearchParams,AbortController,Event,CustomEvent,Date,console,media,
  endpoint:{origin:'http://127.0.0.1:1234',key:'test',series:'test',episode:'1'},
  window:{dispatchEvent(){}},localStorage:{getItem(){return null},setItem(){}},
  document:{createTextNode:text=>({textContent:text}),createElement:tag=>tag==='div'?layer:{dataset:{},style:{},offsetWidth:100,replaceChildren(){}}},
  requestAnimationFrame:fn=>{frames[0]=fn;return 1},cancelAnimationFrame(){frames.length=0},
  fetch:async url=>new URL(url).pathname.endsWith('/emojis')?{ok:true,json:async()=>({items:{}})}:
    new Promise(resolve=>pending.push(page=>resolve({ok:true,json:async()=>page}))) });
vm.runInContext(source + `
const api=createDanmaku({read:async(endpoint,resource,params,signal)=>{
  const url=new URL(endpoint.origin+'/desktop/social/'+resource);url.search=new URLSearchParams(params);
  return (await fetch(url,{signal})).json();},preference:(_,fallback)=>fallback,set(){},
  emojis:{load(){},catalog:Object.create(null),parts:text=>[String(text)],Text(){}}});
const desktopStartDanmaku=api.start;
`,context);
const run = expr=>vm.runInContext(expr,context);
const flush = ()=>new Promise(resolve=>setImmediate(resolve));
async function tick(time){media.currentTime=time;frames.shift()?.();await flush()}
const row=(id,offset_ms,text=id)=>({id,text,offset_ms});
const page=items=>({items,next_offset_ms:0,has_more:true,cursor:String(pending.length)});
context.samples=[row('first',1000,'一样😀[微笑]'),row('copy',1000,'一样😀[微笑]'),
  row('later',20000,'一样😀[微笑]'),row('other',1000,'不同'),
  row('long-a',40000,'长'.repeat(160)+'甲'),row('long-b',40000,'长'.repeat(160)+'乙')];
assert.equal(run('api.rows(samples).length'),5,'deduplicate by full text and exact time, not ID alone or truncated display');
context.samples=[row('first',1000,'相同'),row('copy',1001,'相同')];
assert.equal(run('api.rows(samples).length'),2,'different milliseconds are distinct');
context.samples=[row('same-id',1000,'旧'),row('same-id',2000,'新')];
assert.equal(run('api.rows(samples)[0].text'),'新','existing ID update semantics remain');
(async()=>{
  const stop=run('desktopStartDanmaku(media,endpoint,()=>{})');
  await tick(2);await tick(4);await tick(6);await tick(8);
  pending.shift()(page([row('late',1000),row('ontime',8000),row('a-copy',8000,'ontime'),row('future',9000)]));await flush();await tick(8);
  assert.equal(media.desktopDanmaku.some(r=>r.text==='late'),false,'response-time clock must reject late arrivals');
  assert.equal(media.desktopDanmakuRows.length,3,'raw list preserves original offsets');
  assert.equal(layer.children.length,1);assert.match(layer.children[0].style.transform,/translate3d\(1000px,/,'first frame starts at right edge');
  const original=JSON.stringify(media.desktopDanmaku.find(r=>r.text==='ontime'));
  await tick(8.5);const before=layer.children.find(n=>n.dataset.id==='ontime').style.transform;
  pending.shift()({...page([row('late',1000),row('ontime',8000),row('another-copy',8000,'ontime'),row('future',9000),row('page-late',5000)]),cursor:'second'});await flush();await tick(8.5);
  assert.equal(media.desktopDanmakuRows.filter(r=>r.text==='ontime').length,1,'list removes aliases across pages');
  assert.equal(media.desktopDanmakuRows.find(r=>r.text==='ontime').id,'ontime','first representative ID remains stable');
  assert.equal(JSON.stringify(media.desktopDanmaku.find(r=>r.text==='ontime')),original,'pagination keeps in-flight schedule');
  assert.equal(layer.children.find(n=>n.dataset.id==='ontime').style.transform,before);
  assert.equal(media.desktopDanmaku.some(r=>r.text==='page-late'),false);
  events.get('desktopsocialsettings')({detail:{settings:{opacity:60,lanes:3,fontSize:30,duration:14}}});
  assert.equal(media.desktopDanmaku.filter(r=>r.text==='ontime').length,1,'settings cannot resurrect a duplicate');
  assert.equal(media.desktopDanmaku.some(r=>r.text==='late'||r.text==='page-late'),false,'settings cannot resurrect suppressed rows');
  media.currentTime=70;events.get('seeking')();await tick(70);
  pending.shift()(page([row('stale-generation',71000)]));await flush();await tick(70);
  pending.shift()(page([row('seek-late',60000),row('seek-future',71000)]));await flush();await tick(71);
  assert.equal(media.desktopDanmaku.some(r=>r.text==='seek-late'||r.text==='stale-generation'),false);
  assert.equal(media.desktopDanmaku.some(r=>r.text==='seek-future'),true);
  stage.classList.contains=()=>true;
  events.get('desktopsocialsettings')({detail:{danmaku:false}});
  assert.equal(media.desktopDanmaku.length,0);
  events.get('desktopsocialsettings')({detail:{danmaku:true}});
  pending.shift()(page([row('disabled-request',72000)]));await flush();
  pending.shift()(page([row('reopen-late',70000),row('native-future',72000),row('native-copy',72000,'native-future')]));await flush();await tick(72);
  assert.equal(layer.hidden,true,'native mode hides DOM');
  assert.equal(media.desktopDanmaku.length,1,'reopening admits only future native entries');
  assert.equal(media.desktopDanmaku[0].text,'native-future');
  stop();assert.equal(media.desktopDanmaku.length,0);
  pending.length=0;media.currentTime=0;stage.classList.contains=()=>false;
  const stopAgain=run('desktopStartDanmaku(media,endpoint,()=>{})');
  pending.shift()({items:[row('keep',1000),...Array.from({length:605},(_,i)=>row('dup-'+i,5000,'重复'))],next_offset_ms:30000,has_more:false,cursor:''});
  await flush();await tick(1);
  assert.equal(media.desktopDanmakuRows.length,2,'deduplicate before cache bound, so duplicate floods do not evict unique rows');
  assert.equal(layer.children.length,1);assert.equal(layer.children[0].dataset.id,'keep');
  media.currentTime=0;events.get('seeking')();await tick(0);
  pending.shift()({items:[row('keep',1000),row('copy-after-seek',1000,'keep')],next_offset_ms:30000,has_more:false,cursor:''});
  await flush();await tick(1);
  assert.equal(layer.children.length,1,'seek permits replay without carrying stale dedup state');
  stopAgain();
  console.log('PASS: delayed ingress, exact-time/full-text dedup, cross-page stable ID/position, list, settings, cache bound, seek, reopening, DOM/native timeline and cleanup');
})().catch(error=>{console.error(error);process.exitCode=1});
