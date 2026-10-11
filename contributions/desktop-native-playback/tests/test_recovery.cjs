const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const source=fs.readFileSync(process.argv[2]||path.join(__dirname,'../src/frontend-native.js'),'utf8');
const tick=async()=>{for(let n=0;n<20;n++)await new Promise(setImmediate)};
(async()=>{
 for(const fault of (process.argv[3]?[process.argv[3]]:['unknown-late','teardown-seek','delete-retry','position-reject','size-reject','abandoned-preparation'])){
  let selected=false,failed=false,deletes=0,ready=0,errors=0,args,seekTarget,preparationDisposed=0;
  const timers=new Map();let token=0;
  const media=new EventTarget();Object.assign(media,{playbackRate:2,volume:.4,muted:false,pause(){},play(){return Promise.resolve();},
   closest:()=>({classList:{add(){},remove(){}},querySelector:()=>null}),getBoundingClientRect:()=>({left:0,top:0,width:800,height:600})});
  const context={URL,Event,Number,Math,Date,AbortController,DOMException,queueMicrotask,
   ResizeObserver:class{observe(){}disconnect(){}},window:{devicePixelRatio:1},
   document:{hidden:false,addEventListener(){},removeEventListener(){},head:{append(){}},createElement:()=>({remove(){}})},
   setTimeout(fn,delay){timers.set(++token,{fn,delay});return token;},clearTimeout:id=>timers.delete(id),
   w0:()=>({origin:'http://127.0.0.1',url:'http://127.0.0.1/desktop/hls?ep=1',key:'owned'}),
   desktopCodecHls(...value){args=value;return Object.assign(()=>{},{seek(target){seekTarget=target;value[3].onReady();}});},
   fetch:async(url,init={})=>{
    url=String(url);let body;
    if(init.method==='DELETE'){
     deletes++;
     if(deletes===1&&fault==='delete-retry')throw Error('transient loopback disconnect');
     if(deletes===1&&fault==='teardown-seek'){media.currentTime=55;return {ok:true,status:202,json:async()=>({released:false})};}
     return {ok:true,status:204};
    }
    if(url.endsWith('/capabilities'))body={nativePlayback:1};
    else if(url.endsWith('/mode')){selected=true;body={mode:'native'};}
    else if(url.endsWith('/control'))body={revision:100};
    else if(init.method==='POST')body={id:'a'.repeat(32)};
    else body={state:'complete',duration:fault==='unknown-late'?null:90,source:{video:{contentType:'video/mp4; codecs="hvc1.1"'}},
     native:selected?{state:failed||fault==='abandoned-preparation'?'failed':'ready',revision:100,outputReady:true,width:1920,height:1080,time:37,duration:90}:null};
    return {ok:true,status:200,json:async()=>body};
   }};
  if(fault.endsWith('-reject'))context.window.__TAURI_INTERNALS__={metadata:{currentWindow:{label:'owned'}},invoke:async command=>{if(command.endsWith(fault==='position-reject'?'inner_position':'inner_size'))throw Error('window IPC rejected');return {x:0,y:0,width:800,height:600};}};
  vm.createContext(context);vm.runInContext(source,context);
  const dispose=context.desktopNativePlayback(media,'http://127.0.0.1',0,{onReady(){ready++;},onError(){errors++;}},fault==='abandoned-preparation'?{dispose(){preparationDisposed++;}}:null,true);
  await tick();if(fault.endsWith('-reject')){assert(args,'geometry IPC rejection delegates to HLS');assert.equal(args[6].forceH264,false);assert.equal(errors,0);assert.equal(selected,false);assert.equal(deletes,1);dispose();timers.clear();continue;}if(fault==='abandoned-preparation'){assert.equal(ready,0);assert(args);assert.equal(args[4],null);assert.equal(preparationDisposed,1,'forced fallback disposes the abandoned preparation');dispose();timers.clear();continue;}assert.equal(ready,1);failed=true;
  for(let n=0;n<4&&!args;n++){
   for(const [id,timer] of [...timers])if(timer.delay===250||timer.delay===100){timers.delete(id);await timer.fn();await tick();}
   await tick();
  }
  assert.equal(errors,0,fault);assert(args,fault+' must recover');
  assert.equal(args[6].forceH264,true);
  if(fault==='unknown-late'){
   assert.equal(args[2],0,'late unknown-duration native failure must restart HLS at zero');assert.equal(args[5],false);
   args[3].onReady();await tick();assert.equal(seekTarget,37,'late fallback retains the current playback position');
  }else if(fault==='teardown-seek')assert.equal(args[2],55,'currentTime writes during 202 teardown survive handoff');
  else if(fault==='abandoned-preparation'){assert.equal(preparationDisposed,1,'forced fallback disposes the abandoned preparation');assert.equal(args[4],null);}
  else assert.equal(deletes,2,'transient DELETE transport failures are retried');
  dispose();timers.clear();
 }
 console.log('PASS: late unknown-duration fallback, teardown currentTime writes and transient DELETE retry');
})().catch(error=>{console.error(error);process.exitCode=1;});
