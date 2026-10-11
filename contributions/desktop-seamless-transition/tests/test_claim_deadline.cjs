const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
(async()=>{
 for(const probe of ['capability','window'])for(const cancel of [false,true]){
  let now=0,token=0,released=0,retired=0;const timers=new Map(),url='http://127.0.0.1/desktop/hls?ep=2';
  const c={WeakMap,Map,Number,Math,AbortController,Date:{now:()=>now},
   setTimeout(fn,delay){timers.set(++token,{fn,delay});return token;},clearTimeout:id=>timers.delete(id),
   w0:()=>({origin:'http://127.0.0.1',url,key:'owned'}),
   desktopSupportsSource:()=>new Promise(()=>{}),desktopNativeWindowContext:()=>new Promise(()=>{}),
   fetch:async(url,init={})=>{
    let body;if(init.method==='DELETE'){released++;return {ok:true,status:204};}
    if(String(url).endsWith('/capabilities'))body={standbyPlayback:1,nativePlayback:probe==='window'?1:0};
    else if(init.method==='POST')body={id:'b'.repeat(32)};
    else body={state:'complete',duration:90,source:{video:{contentType:'video/mp4; codecs="hvc1.1"'}}};
    return {ok:true,status:200,json:async()=>body};
   }};
  vm.createContext(c);vm.runInContext(fs.readFileSync(process.argv[2]||path.join(__dirname,'../src/frontend-seamless.js'),'utf8'),c);
  const current={desktopSessionId:()=> 'a'.repeat(32)},prep=c.desktopPrepareNext(url,current);
  for(let n=0;n<20;n++)await new Promise(setImmediate);
  now=10000;prep.retain(()=>retired++);let settled=false;
  const pending=prep.claimRecord(url,0).then(v=>{settled=true;return v;});
  if(cancel)prep.cancelClaim(true);else {now=90000;const timer=[...timers.values()].find(t=>t.delay===80000);assert(timer,'claim uses remaining original deadline');timer.fn();}
  for(let n=0;n<20;n++)await new Promise(setImmediate);
  assert(settled,'claimed preparation cannot wait forever on a stalled probe');assert.equal(await pending,null);
  assert.equal(released,1);assert.equal(retired,0);prep.finishRetained();assert.equal(retired,1);timers.clear();
 }
 console.log('PASS claimed capability/window probe timeout and abort preserve cold fallback');
})().catch(e=>{console.error(e);process.exitCode=1;});
