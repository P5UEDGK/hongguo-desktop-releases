const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[2]||path.join(__dirname,'../src/frontend-codec.js'),'utf8');
const tick=async()=>{for(let i=0;i<20;i++)await new Promise(setImmediate);};
(async()=>{
 for(const entry of ['direct','no-resize']) for(const windowed of [false,true]) for(const known of [false,true]){
  const calls=[],seeks=[];let errors=0,ready=0,released=0;
  const media=new EventTarget();Object.assign(media,{currentTime:0,playbackRate:2,volume:.4,muted:true,paused:false,
   play(){this.paused=false;this.dispatchEvent(new Event('play'));return Promise.resolve();},pause(){this.paused=true;this.dispatchEvent(new Event('pause'));}});
  const url='http://127.0.0.1/desktop/hls?ep=1',id='a'.repeat(32);
  const context={URL,Headers,Event,AbortController,Number,Math,Map,Date,queueMicrotask,setTimeout,clearTimeout,
   w0:()=>({origin:'http://127.0.0.1',url,key:'owned'}),
   fetch:async()=>({ok:true,clone(){return this;},json:async()=>({state:'failed',failureCode:'start-position',duration:known?10:null,videoMode:'h264'})})};
  function legacy(kind,target,requested,position,callbacks,preparation,transport){
   const index=calls.length;calls.push({kind,position});
   const controller=Object.assign(()=>released++,{seek(value){seeks.push(value);media.currentTime=value;callbacks.onReady();}});
   queueMicrotask(async()=>{if(index===0){await transport('http://127.0.0.1/desktop/hls/'+id+'/status');callbacks.onError();}else callbacks.onReady();});
   return controller;
  }
  context.desktopLegacyHls=(target,requested,position,callbacks,prep,unused,transport)=>legacy('legacy',target,requested,position,callbacks,prep,transport);
  context.ek=(target,requested,position,callbacks,prep,transport)=>legacy('windowed',target,requested,position,callbacks,prep,transport);
  vm.createContext(context);vm.runInContext(source,context);
  if(entry==='no-resize')vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/frontend-native.js'),'utf8'),context);
  const dispose=context[entry==='direct'?'desktopCodecHls':'desktopNativePlayback'](media,url,30,{onReady(){ready++;},onError(){errors++;}},null,windowed);
  media.pause();await tick();await tick();
  assert.equal(errors,0,'unknown-duration direct HLS resume recovers start-position failure');
  assert.deepEqual(calls,[{kind:windowed?'windowed':'legacy',position:30},{kind:'legacy',position:0}]);
  assert.deepEqual(seeks,known?[]:[30],'zero-origin recovery preserves the saved position as explicit seek');
  assert.equal(media.currentTime,known?0:30);assert.equal(media.playbackRate,2);assert.equal(media.paused,true);assert.equal(ready,1);assert.equal(released,1);
  dispose();assert.equal(released,2);
 }
 console.log('PASS direct HLS and missing ResizeObserver recover unknown-duration resume with pending seek');
})().catch(e=>{console.error(e);process.exitCode=1;});
