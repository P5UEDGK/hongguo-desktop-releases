const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/danmaku.mjs'), 'utf8').replace('export function', 'function');
const row = (id, offset_ms, text=id) => ({id, offset_ms, text});
const failures = [];
async function test(name, fn) {try {await fn();console.log('PASS:',name);} catch(e) {failures.push(name);console.error('FAIL:',name,e.message);}}
function fixture() {
  let now=0, frame;
  const pending=[], events=new Map(), statuses=[];
  const layer={children:[],setAttribute(){},append(n){this.children.push(n);n.remove=()=>this.children=this.children.filter(x=>x!==n);},replaceChildren(){this.children=[];},remove(){}};
  const stage={classList:{contains:()=>false},append(){}};
  const media={currentTime:0,duration:1200,playbackRate:1,clientWidth:1000,clientHeight:646,
    closest:()=>stage,dispatchEvent(){},addEventListener:(n,f)=>events.set(n,f),removeEventListener:n=>events.delete(n)};
  const context=vm.createContext({console,AbortController,Event,Date:class extends Date {static now(){return now;}},
    localStorage:{getItem(){return null;},setItem(){}},window:{},
    document:{createTextNode:text=>({textContent:text}),createElement:tag=>tag==='div'?layer:{dataset:{},style:{},offsetWidth:60,replaceChildren(){}}},
    requestAnimationFrame:f=>{frame=f;return 1;},cancelAnimationFrame(){frame=null;},
    read:(_,__,params)=>new Promise((resolve,reject)=>pending.push({params,resolve,reject}))});
  vm.runInContext(source+'\nthis.api=createDanmaku({read,preference:(_,v)=>v,set(){},emojis:{load(){},catalog:{},parts:t=>[t]}});',context);
  const flush=()=>new Promise(r=>setImmediate(r));
  return {api:context.api,media,events,pending,statuses,layer,context,
    async tick(time){now+=Math.max(0,time-media.currentTime)*1000;media.currentTime=time;frame?.();await flush();},
    async resolve(page){pending.shift().resolve({items:[],next_offset_ms:30000,cursor:'',has_more:false,...page});await flush();},
    async reject(){pending.shift().reject(Error('offline'));await flush();},
    start(){return context.api.start(media,{},s=>statuses.push(s));},
    settings:{opacity:80,lanes:6,fontSize:18,duration:4}};
}
(async()=>{
  await test('same bucket pagination preserves its opaque cursor while paused',async()=>{
    const f=fixture();f.media.currentTime=25;const stop=f.start();
    assert.equal(f.pending[0].params.offset_ms,0);
    await f.resolve({next_offset_ms:0,has_more:true,cursor:'second'});
    await f.tick(25);
    assert.equal(f.pending[0].params.cursor,'second');
    await f.resolve({next_offset_ms:0,has_more:true,cursor:'third'});
    await f.tick(25);assert.equal(f.pending[0].params.cursor,'third');stop();
  });
  await test('late-only raw pages are not repeatedly sorted while paused',async()=>{
    const f=fixture();const stop=f.start();await f.tick(2);
    await f.resolve({items:Array.from({length:600},(_,i)=>row(String(i),i)),next_offset_ms:30000});
    await f.tick(2);let evaluations=0;
    f.context.JSON={...JSON,stringify(...args){evaluations++;return JSON.stringify(...args);}};
    for(let i=0;i<60;i++)await f.tick(2);
    assert.equal(evaluations,0);assert.equal(f.media.desktopDanmaku.length,0);stop();
  });
  await test('closing settings stays closed after restoring toggle focus',()=>{
    const values=[true,false,{opacity:80,lanes:3,fontSize:28,duration:14},true,[]];let index=0,root,focused=false;
    const React={useState(initial){const i=index++;return [values[i],value=>{values[i]=value;}];},
      useRef:()=>({current:null}),useEffect(){},useLayoutEffect(){}};
    const jsx=(type,props)=>({type,props});
    const context=vm.createContext({clearTimeout,localStorage:{getItem:()=>null}});
    vm.runInContext(source+'\nthis.create=createDanmaku;',context);
    const api=context.create({React,jsxRuntime:{jsx,jsxs:jsx},read(){},preference:(_,v)=>v,set(){},emojis:{}});
    root=api.Settings({media:{current:null},sessionKey:'fixture'});
    root.props.ref.current={querySelector:()=>({focus(){focused=true;root.props.onFocus();}})};
    const close=root.props.children[1].props.children[0].props.children[2];
    close.props.onClick();assert.equal(focused,true);assert.equal(values[0],false);
  });
  await test('schedule cap reserves active and nearest future rows',()=>{
    const {api,settings}=fixture();const dense=Array.from({length:600},(_,i)=>row(String(i),i*100,'字'));
    const first=api.rows(dense,settings);
    const next=api.rows(dense,settings,first,1000,25000);
    assert.equal(next.length,300);assert.ok(next.some(r=>r.offset_ms===24900));
    assert.ok(next.some(r=>r.offset_ms===25000));assert.ok(next.at(-1).offset_ms<59900);
  });
  await test('duration and font changes revalidate future lane spacing',()=>{
    const {api,settings}=fixture();const pair=[row('a',0,'甲'),row('b',1000,'乙')], one={...settings,lanes:1};
    const before=api.rows(pair,one);
    const after=api.rows(pair,{...one,duration:24},before,1000,200);
    assert.ok(after.some(r=>r.id==='a'));assert.equal(after.some(r=>r.id==='b'),false);
    const narrow=api.rows(pair,one,before,100,200);
    assert.equal(narrow.some(r=>r.id==='b'),false);
  });
  await test('dense schedule rolls forward without resurrecting late rows',async()=>{
    const f=fixture(), stop=f.start();
    f.events.get('desktopsocialsettings')({detail:{settings:f.settings}});
    await f.resolve({items:Array.from({length:600},(_,i)=>row(String(i),i*100,'字')),next_offset_ms:60000});
    await f.tick(0);assert.ok(f.layer.children.some(n=>n.dataset.id==='0'),'initial near-time rows are not replaced by far future rows');
    for(let t=1;t<=35;t++)await f.tick(t);
    assert.ok(f.media.desktopDanmaku.some(r=>r.offset_ms===35000),'future rows beyond first cap remain schedulable');
    assert.ok(f.layer.children.some(n=>n.dataset.id==='350'));
    stop();
  });
  await test('late dense page cannot evict an admitted in-flight row',async()=>{
    const f=fixture(),stop=f.start();
    await f.resolve({items:[row('active',1000)],next_offset_ms:0,has_more:true,cursor:'more'});
    await f.tick(2);
    await f.resolve({items:Array.from({length:600},(_,i)=>row('late'+i,i)),next_offset_ms:30000});
    assert.ok(f.media.desktopDanmaku.some(r=>r.text==='active'));
    stop();
  });
  await test('slowing duration does not resurrect an already finished row',async()=>{
    const f=fixture(),stop=f.start();
    f.events.get('desktopsocialsettings')({detail:{settings:f.settings}});
    await f.resolve({items:[row('finished',0)]});
    for(let t=1;t<=5;t++)await f.tick(t);
    f.events.get('desktopsocialsettings')({detail:{settings:{...f.settings,duration:24}}});
    await f.tick(5);assert.equal(f.layer.children.length,0);
    stop();
  });
  await test('outage recovery reads current bucket and clears stale cursor',async()=>{
    const f=fixture(),stop=f.start();
    await f.resolve({items:[],next_offset_ms:0,cursor:'stale',has_more:true});
    await f.tick(0);await f.reject();
    for(let t=1;t<=600;t++){await f.tick(t);if(f.pending.length && t<600)await f.reject();}
    const request=f.pending.at(-1);assert.ok(request);
    assert.equal(request.params.offset_ms,600000);assert.equal(request.params.cursor,'');stop();
  });
  await test('disabling clears retry status and narrowing revalidates future rows',async()=>{
    const f=fixture(),stop=f.start();await f.reject();
    assert.match(f.statuses.at(-1),/失败/);
    f.events.get('desktopsocialsettings')({detail:{danmaku:false}});
    assert.equal(f.statuses.at(-1),'');stop();
    const g=fixture(),close=g.start();g.events.get('desktopsocialsettings')({detail:{settings:{...g.settings,lanes:1}}});
    await g.resolve({items:[row('a',0,'甲'),row('b',1000,'乙')],next_offset_ms:30000});
    await g.tick(.2);g.media.clientWidth=100;await g.tick(.3);
    assert.equal(g.media.desktopDanmaku.some(r=>r.text==='乙'),false);close();
  });
  if(failures.length)throw Error(failures.length+' regressions failed');
})().catch(e=>{console.error(e);process.exitCode=1;});
