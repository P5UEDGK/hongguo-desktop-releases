const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const tick=async()=>{for(let n=0;n<10;n++)await new Promise(setImmediate)};
(async()=>{
 for(const fail of [false,true]) for(const pausePhase of ['none','claim','seek']){
  let resolveClaim,adopted=false,cold=false,cancelled=false,position=0;
  let coldPaused;const calls=[],media=new EventTarget();Object.assign(media,{playbackRate:2,volume:.4,muted:false,paused:false,
   closest:()=>null,getBoundingClientRect:()=>({width:800,height:600}),pause(){this.paused=true;},play(){return Promise.resolve();}});
  const prep={claimRecord:()=>new Promise(resolve=>resolveClaim=resolve),cancelClaim(keep){assert(keep);cancelled=true;},dispose(){}};
  const context={URL,Event,Number,Math,Map,AbortController,setTimeout,clearTimeout,
   ResizeObserver:class{observe(){}disconnect(){}},document:{hidden:false,removeEventListener(){},head:{append(){}},createElement:()=>({remove(){}})},window:{},
   w0:()=>({origin:'http://127.0.0.1',url:'http://127.0.0.1/desktop/hls?ep=2',key:'test'}),
   desktopCodecHls(target,url,start,callbacks,preparation,windowed,intent){cold=true;coldPaused=intent.paused;assert.equal(start,20);return ()=>{};}};
  vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),context);
  const dispose=context.desktopNativePlayback(media,'http://127.0.0.1',0,{onSeekTarget(){},onError(){throw Error('unexpected failure');}},prep);
  dispose.seek(20);
  if(pausePhase==='claim')media.pause();
  resolveClaim({mode:'copy',async seek(target){calls.push('seek');assert.equal(target,20);if(pausePhase==='seek')media.pause();await tick();if(fail)throw Error('seek rejected');position=target;},
   adopt(){calls.push('activate');assert.equal(position,20,'pending claim seek is ACKed before HLS activation');adopted=true;return Object.assign(()=>{},{seek(){}});}});
  await tick();await tick();assert.equal(adopted,!fail);assert.equal(cold,fail);assert.equal(cancelled,fail);
  assert.equal(calls[0],'seek');if(pausePhase!=='none'){assert.equal(media.paused,true,'pause during claim or seek survives adoption');if(fail)assert.equal(coldPaused,true,'fallback retains pending pause');}dispose();
 }
 console.log('PASS: pending claim seek precedes HLS adoption, and failed seek falls back at the latest target');
})().catch(error=>{console.error(error);process.exitCode=1;});
