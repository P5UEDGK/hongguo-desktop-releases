const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nativeSource=fs.readFileSync(process.argv[2],'utf8'),codecSource=fs.readFileSync(process.argv[3],'utf8');
const tick=async()=>{for(let n=0;n<20;n++)await new Promise(setImmediate);};
(async()=>{
 const stage={classList:{add(){},remove(){}},querySelector:()=>null},media=new EventTarget();let call,errors=0;
 Object.assign(media,{playbackRate:2,volume:.5,muted:false,currentTime:0,closest:()=>stage,getBoundingClientRect:()=>({left:0,top:0,width:800,height:600}),pause(){},play(){return Promise.resolve();}});
 const preparation={resumePosition:30,resumeFailed:true,dispose(){},async claimRecord(){await tick();dispose.seek(88);return null;}};
 const context={URL,Headers,Event,AbortController,Number,Math,Date,Map,queueMicrotask,window:{devicePixelRatio:1},ResizeObserver:class{observe(){}disconnect(){}},document:{hidden:false,addEventListener(){},removeEventListener(){}},setTimeout:()=>1,clearTimeout(){},
  w0:()=>({origin:'http://127.0.0.1',url:'http://127.0.0.1/desktop/hls?ep=2',key:'owned'}),
  desktopLegacyHls(m,u,position,callbacks){call={position,preserve:callbacks.preserveResumePosition};return Object.assign(()=>{},{seek(){}});}
 };
 context.ek=(m,u,p,cb)=>context.desktopLegacyHls(m,u,p,cb);
 vm.createContext(context);vm.runInContext(codecSource,context);vm.runInContext(nativeSource,context);
 const dispose=context.desktopNativePlayback(media,'http://127.0.0.1',30,{onReady(){},onError(){errors++;}},preparation,true);
 await tick();await tick();assert.equal(errors,0);assert(call);assert.equal(call.position,88);assert.equal(call.preserve,true,'null standby still carries explicit near-EOF seek into the actual codec wrapper');dispose();
 console.log('PASS null-standby cold HLS preserves queued near-EOF user seek');
})().catch(e=>{console.error(e);process.exitCode=1;});
