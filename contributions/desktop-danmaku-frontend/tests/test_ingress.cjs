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
const row=(id,offset_ms)=>({id,text:id,offset_ms});
const page=items=>({items,next_offset_ms:0,has_more:true,cursor:String(pending.length)});
(async()=>{
  const stop=run('desktopStartDanmaku(media,endpoint,()=>{})');
  await tick(2);await tick(4);await tick(6);await tick(8);
  pending.shift()(page([row('late',1000),row('ontime',8000),row('future',9000)]));await flush();await tick(8);
  assert.equal(media.desktopDanmaku.some(r=>r.text==='late'),false,'response-time clock must reject late arrivals');
  assert.equal(media.desktopDanmakuRows.length,3,'raw list preserves original offsets');
  assert.equal(layer.children.length,1);assert.match(layer.children[0].style.transform,/translate3d\(1000px,/,'first frame starts at right edge');
  const original=JSON.stringify(media.desktopDanmaku.find(r=>r.text==='ontime'));
  await tick(8.5);const before=layer.children.find(n=>n.dataset.id==='ontime').style.transform;
  pending.shift()({...page([row('late',1000),row('ontime',8000),row('future',9000),row('page-late',5000)]),cursor:'second'});await flush();await tick(8.5);
  assert.equal(JSON.stringify(media.desktopDanmaku.find(r=>r.text==='ontime')),original,'pagination keeps in-flight schedule');
  assert.equal(layer.children.find(n=>n.dataset.id==='ontime').style.transform,before);
  assert.equal(media.desktopDanmaku.some(r=>r.text==='page-late'),false);
  events.get('desktopsocialsettings')({detail:{settings:{opacity:60,lanes:3,fontSize:30,duration:14}}});
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
  pending.shift()(page([row('reopen-late',70000),row('native-future',72000)]));await flush();await tick(72);
  assert.equal(layer.hidden,true,'native mode hides DOM');
  assert.equal(media.desktopDanmaku.length,1,'reopening admits only future native entries');
  assert.equal(media.desktopDanmaku[0].text,'native-future');
  stop();assert.equal(media.desktopDanmaku.length,0);
  console.log('PASS: delayed response, right-edge first frame, pagination continuity, settings, seek generation, reopening, native timeline and cleanup');
})().catch(error=>{console.error(error);process.exitCode=1});
