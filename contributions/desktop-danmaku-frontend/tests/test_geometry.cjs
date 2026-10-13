const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const CustomEvent = globalThis.CustomEvent || class extends Event {constructor(type,options){super(type);this.detail=options.detail;}};
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname,'../src/danmaku.mjs'),'utf8').replace('export function','function');
let frames = [], requests = [], errors = [], events = new Map();
const preferences = new Map(); let preferenceEvent;
const layer = {children: [], hidden: false, setAttribute(){}, append(node){this.children.push(node); node.remove=()=>this.children=this.children.filter(n=>n!==node);}, replaceChildren(){this.children=[];}, remove(){this.removed=true;}};
const stage = {clientWidth:1000,classList:{contains:()=>false},append(){}};
const media = {currentTime:0,duration:192,clientWidth:1000,closest:()=>stage,
  dispatchEvent(){},addEventListener:(name,fn)=>events.set(name,fn),removeEventListener:name=>events.delete(name)};
const context = vm.createContext({URL,URLSearchParams,AbortController,Event,CustomEvent,Date,console,
  localStorage:{getItem:key=>preferences.get(key)??null,setItem:(key,value)=>preferences.set(key,value)},
  window:{dispatchEvent(){}},
  document:{createTextNode:text=>({textContent:text}),createElement:tag=>tag==='div'?layer:{dataset:{},style:{},offsetWidth:100,replaceChildren(...nodes){this.children=nodes;this.textContent=nodes.map(n=>n.textContent||'').join('');}}},
  requestAnimationFrame:fn=>{frames.push(fn);return frames.length;},cancelAnimationFrame(){},
  fetch:async(url,options)=>{if(new URL(url).pathname.endsWith('/emojis'))return {ok:true,json:async()=>({items:{}})};requests.push({url:new URL(url),options});return {ok:true,json:async()=>({items:[
    {id:'3000000000000000001',text:'<img onerror=alert(1)>',offset_ms:1000}],next_offset_ms:30000,cursor:'opaque',has_more:true})};}});
vm.runInContext(source + `
const preferencesRead=(name,fallback)=>localStorage.getItem('hongguo:'+name)===null?fallback:localStorage.getItem('hongguo:'+name)==='on';
const api=createDanmaku({read:async(endpoint,resource,params,signal)=>{
 const url=new URL(endpoint.origin+'/desktop/social/'+resource); url.search=new URLSearchParams(params);
 const r=await fetch(url,{signal}); return r.json();},preference:preferencesRead,
 set:(media,changes)=>{for(const name of ['social','danmaku'])if(typeof changes[name]==='boolean')localStorage.setItem('hongguo:'+name,changes[name]?'on':'off');
 if(changes.settings){changes.settings=api.settings(changes.settings);localStorage.setItem('hongguo:danmakuSettings',JSON.stringify(changes.settings));localStorage.setItem('hongguo:danmakuSettingsVersion','2');}
 media.dispatchEvent(new CustomEvent('desktopsocialsettings',{detail:changes}));},
 emojis:{load(){},catalog:Object.create(null),parts:text=>[String(text)],Text(){}}});
const desktopStartDanmaku=api.start,desktopDanmakuRows=api.rows,desktopDanmakuSettings=api.settings;
const desktopSocialPreference=preferencesRead,desktopSocialSet=(media,changes)=>{
for(const name of ['social','danmaku'])if(typeof changes[name]==='boolean')localStorage.setItem('hongguo:'+name,changes[name]?'on':'off');
if(changes.settings){changes.settings=api.settings(changes.settings);localStorage.setItem('hongguo:danmakuSettings',JSON.stringify(changes.settings));localStorage.setItem('hongguo:danmakuSettingsVersion','2');}
media.dispatchEvent(new CustomEvent('desktopsocialsettings',{detail:changes}));};
`, context);
const run = expression => vm.runInContext(expression, context);
context.media=media; context.endpoint={origin:'http://127.0.0.1:1234',key:'abc',series:'1000000000000000001',episode:'1'};
async function step(time){media.currentTime=time;frames.shift()?.();await new Promise(r=>setImmediate(r));}
(async()=>{
 media.clientHeight=562;media.videoWidth=180;media.videoHeight=320;
 const stop=run('desktopStartDanmaku(media,endpoint,()=>{})');
 await new Promise(r=>setImmediate(r));await step(2);
 const node=layer.children[0];assert(node);
 assert.equal(parseFloat(node.style.fontSize),15.75,'Portrait glyphs use the contained short side');
 assert(node.style.clipPath.startsWith('inset(0 '));
 const portrait=node.style.transform;
 media.videoWidth=320;media.videoHeight=180;await step(2);
 assert.equal(parseFloat(node.style.fontSize),28);
 assert.notEqual(node.style.transform,portrait);
 media.clientWidth=720;media.clientHeight=500;await step(2);
 assert(Math.abs(parseFloat(node.style.fontSize)-20.18)<.02);
 const frozen=node.style.transform;await step(2);assert.equal(node.style.transform,frozen);
 for(let time=2.5;time<=14.5;time+=.5)await step(time);
 assert(/px 0 [1-9]/.test(node.style.clipPath),'Left exit is clipped to the visible video');
 stop();assert.equal(media.desktopDanmaku.length,0);
 console.log('PASS: portrait/landscape/resize glyph scale, contained motion, clipping, pause and cleanup');
})().catch(e=>{console.error(e);process.exitCode=1});
