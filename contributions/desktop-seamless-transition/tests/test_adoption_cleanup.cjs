const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const tick=async()=>{for(let n=0;n<10;n++)await new Promise(setImmediate)};
(async()=>{
for(const fault of process.argv[3]?[process.argv[3]]:['cancel-replay','empty-adopt']){
 let resolveClaim,dispose,cold=0,restored=0,retained=0;const media=new EventTarget();
 Object.assign(media,{playbackRate:1,volume:.5,muted:false,paused:false,closest:()=>null,getBoundingClientRect:()=>({width:800,height:600}),pause(){this.paused=true;},play(){return Promise.resolve();}});
 const original=media.play;
 const prep={claimRecord:()=>new Promise(resolve=>resolveClaim=resolve),cancelClaim(keep){if(keep)retained++;},dispose(){}};
 const context={URL,Event,Number,Math,Map,AbortController,setTimeout,clearTimeout,ResizeObserver:class{observe(){}disconnect(){}},document:{hidden:false,removeEventListener(){},head:{append(){}},createElement:()=>({remove(){}})},window:{},w0:()=>({origin:'http://127.0.0.1',url:'http://127.0.0.1/desktop/hls?ep=2',key:'test'}),desktopCodecHls(){cold++;return ()=>{};}};
 vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),context);
 dispose=context.desktopNativePlayback(media,'http://127.0.0.1',0,{onReady(){dispose();},onError(){throw Error('unexpected');}},prep);
 resolveClaim({mode:'h264',adopt(target,callbacks){if(fault==='empty-adopt')return null;target.play=()=>Promise.resolve();callbacks.onReady();return ()=>{target.play=original;restored++;};},dispose(){}});
 await tick();
 if(fault==='cancel-replay'){assert.equal(restored,1);assert.equal(media.play,original);assert.equal(cold,0);}
 else{assert.equal(cold,1,'empty adoption falls back to cold HLS');assert.equal(retained,1);dispose();}
}
console.log('PASS adoption callback cancellation unwinds and empty adoption falls back');
})().catch(error=>{console.error(error);process.exitCode=1;});
