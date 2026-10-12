const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[2]||path.join(__dirname,'../src/frontend-native.js'),'utf8');
const tick=async()=>{for(let n=0;n<30;n++)await new Promise(r=>setTimeout(r,1));};
(async()=>{for(const fault of ['lost-native','stalled-native','lost-h264','conflict-native','initial-property','uncommitted']){
 let committed=null,errors=0,ready=0,fallbacks=0,posts=0,deletes=0;const timers=new Map(),nativeTimers=new Set();let token=0;
 const stage={classList:{add(){},remove(){}},querySelector:()=>null},media=new EventTarget();
 Object.assign(media,{playbackRate:2,volume:.5,muted:false,closest:()=>stage,getBoundingClientRect:()=>({left:0,top:0,width:800,height:600}),pause(){},play(){return Promise.resolve();}});
 const context={URL,Event,AbortController,Number,Math,Date,window:{devicePixelRatio:1},ResizeObserver:class{observe(){}disconnect(){}},document:{hidden:false,addEventListener(){},removeEventListener(){}},
  setTimeout(fn,delay){if(delay>=15000){const t=setTimeout(fn,1);nativeTimers.add(t);return t;}const id='queued'+(++token);timers.set(id,{fn,delay});return id;},clearTimeout(id){if(timers.has(id))timers.delete(id);else{clearTimeout(id);nativeTimers.delete(id);}},
  w0:()=>({origin:'http://127.0.0.1',url:'http://127.0.0.1/desktop/hls?ep=1',key:'owned'}),
  desktopCodecHls(m,u,p,callbacks,preparation){fallbacks++;assert(['lost-h264','uncommitted'].includes(fault));if(fault==='lost-h264')assert(preparation);return ()=>{};},
  async fetch(url,init={}){url=String(url);let body={};
   if(init.method==='DELETE'){deletes++;return {ok:true,status:204};}
   if(url.endsWith('/capabilities')){if(fault==='initial-property')media.currentTime=12;body={nativePlayback:1};}
   else if(url.endsWith('/mode')){posts++;if(fault==='uncommitted')throw TypeError('POST never arrived');committed=fault==='lost-h264'?'h264':'native';if(fault==='stalled-native')return new Promise(()=>{});if(fault==='conflict-native')return {ok:false,status:409};throw TypeError('lost loopback response');}
   else if(url.endsWith('/status'))body={state:'complete',duration:90,videoMode:committed,source:{video:{contentType:'video/mp4; codecs="hvc1.1"'}},native:committed==='native'?{state:'ready',outputReady:true,revision:0,width:800,height:600,duration:90,time:0,paused:false,seeking:false}:null};
   else if(init.method==='POST')body={id:'a'.repeat(32)};
   return {ok:true,status:200,json:async()=>body};}
 };
 vm.createContext(context);vm.runInContext(source,context);
 const dispose=context.desktopNativePlayback(media,'http://127.0.0.1',0,{onReady(){ready++;},onError(){errors++;}},null);
 await tick();assert.equal(errors,0,fault+' reconciles committed mode before failing');assert.equal(posts,1);assert.equal(deletes,fault==='uncommitted'?1:0,'usable session stays owned; uncommitted native attempt is released');
 assert.equal(fallbacks,['lost-h264','uncommitted'].includes(fault)?1:0);if(!['lost-h264','uncommitted'].includes(fault))assert.equal(ready,1);
 if(fault==='initial-property')assert.equal(media.currentTime,12,'initial negotiation preserves property seeks');
 dispose();await tick();for(const timer of nativeTimers)clearTimeout(timer);timers.clear();
}console.log('PASS lost, timed-out and conflicting native mode replies reconcile committed native/HLS state');})().catch(e=>{console.error(e);process.exitCode=1;});
