// Execute the library owner extracted from a built host bundle, not its source copy.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {Event, EventTarget} = globalThis;

const file = process.argv[2];
assert(file, 'Usage: node test_desktop_library_bundle.cjs <decoded-host-bundle.js>');
const source = fs.readFileSync(file, 'utf8');
const start = source.indexOf('function desktopLibraryCancelled(');
const end = source.indexOf('function Du(', start);
assert(start >= 0 && end > start, 'Host library owner boundaries are missing');
const moduleSource = source.slice(start, end);
const seed = {seriesId:'8800000000000007007', title:'宿主验收第七季', tags:['漫剧'], actors:[], episodeCount:2};
const other = {...seed, seriesId:'8800000000000007006', title:'宿主验收第六季'};
const album = '8800000000000007000';
const storage = new Map();
const native = new Map();
let searches = 0;

function boot() {
  const api = {
    validationStatus:async()=>({baseUrl:'http://127.0.0.1:12345'}),
    favorites:async()=>[...native.values()], history:async()=>[],
    setFavorite:async(item,value)=>{value?native.set(item.seriesId,item):native.delete(item.seriesId);},
    searchNovelfm:async()=>{searches++;return {items:[other]};}
  };
  const context = vm.createContext({
    URL, AbortController, Event, setTimeout, clearTimeout, queueMicrotask, Date,
    window:new EventTarget(), document:{createElement:()=>({}),head:{append(){}}},
    localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)},
    ge:api, Ts:()=>({base:'宿主验收'}), qR:()=>{}, O:{}, b:{},
    KR:async proxy=>({...(await proxy.searchNovelfm('宿主验收',1,'manju')),incomplete:false}),
    fetch:async(url,options)=>({ok:true,json:async()=>({
      requestToken:'test-only',manual:{},relations:[seed,other].map((row,index)=>({
        seriesId:row.seriesId,title:row.title,albumId:album,season:index===0?7:6,state:'resolved',retryAt:0
      }))
    })})
  });
  vm.runInContext(moduleSource, context, {timeout:5000});
  return {api, store:vm.runInContext('desktopLibrary',context)};
}
const settle = async()=>{for(let i=0;i<50;i++)await new Promise(setImmediate);};
(async()=>{
  let instance = boot();
  await instance.api.setFavorite(seed,true);await settle();
  assert(native.has(seed.seriesId),'Current season must save immediately');
  assert(native.has(other.seriesId),'Installed favorite callback did not collect another verified season');
  assert.equal(searches,1,'First favorite must use one shared discovery task');
  for(let i=0;i<5;i++){
    await instance.api.setFavorite(seed,false);
    await instance.api.setFavorite(seed,true);
  }
  await settle();assert.equal(searches,1,'Repeated toggles must reuse successful discovery');
  await instance.api.setFavorite(other,false);await settle();
  await instance.api.setFavorite(seed,true);await settle();
  assert(!native.has(other.seriesId),'Explicitly removed season must remain excluded');
  instance=boot();await instance.api.setFavorite(seed,true);await settle();
  assert.equal(searches,1,'Restart must reuse persisted discovery');
  assert(!native.has(other.seriesId),'Restart must preserve explicit exclusion');
  console.log('PASS built host: favorite callback, verified collection, repeated toggles, restart cache and exclusion');
})().catch(error=>{console.error(error);process.exitCode=1;});
