const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[2],'utf8');
const tick=async()=>{for(let n=0;n<30;n++)await new Promise(setImmediate)};
async function scenario(fault){
  let now=0,errors=0,released=0,finished=0,cancelled=0,selected=true,activated=false;
  const timers=new Set(),scheduled=[],commands=[];
  const media=new EventTarget();Object.assign(media,{playbackRate:2,volume:.4,muted:false,
    closest:()=>({classList:{add(){},remove(){}}}),
    getBoundingClientRect:()=>({left:0,top:0,width:800,height:600})});
  const prep={claimRecord:async()=>fault==='copy-fallback'?{mode:'copy',settings:{rate:3,volume:.2,muted:true},
      adopt(target,handlers,onFailure){
        assert.equal(target.playbackRate,3);assert.equal(target.volume,.2);assert.equal(target.muted,true);
        queueMicrotask(onFailure);return ()=>{};
      }}:{id:'a'.repeat(32),mode:'native',source:{video:{contentType:'video/mp4; codecs="hvc1.1"'}},dispose(){}},dispose(){},
    finishRetained(){if(fault==='success')assert(activated,'old picture retained until activate ACK');finished++},cancelClaim(){cancelled++}};
  const context={URL,Event,Number,Math,Map,AbortController,window:{devicePixelRatio:1},
    Date:{now:()=>now},ResizeObserver:class{observe(){}disconnect(){}},
    document:{hidden:false,head:{append(){}},createElement:()=>({remove(){}}),addEventListener(){},removeEventListener(){}},
    setTimeout(fn,delay){scheduled.push(delay);if(delay>=15000||(fault==='cancel-pending'&&delay>10000))return 999;const id=setTimeout(()=>{now+=250;fn()},1);timers.add(id);return id;},
    clearTimeout:id=>{timers.delete(id);clearTimeout(id)},
    w0:()=>({origin:'http://127.0.0.1',url:'http://127.0.0.1/desktop/hls?ep=2',key:'test'}),
    desktopCodecHls(target){
      assert.equal(fault,'copy-fallback');assert.equal(target.playbackRate,3);
      assert.equal(target.volume,.2);assert.equal(target.muted,true);activated=true;
      return ()=>{};
    },
    fetch:async(url,init={})=>{
      let body={};url=String(url);
      if(init.method==='DELETE'){released++;return {ok:true,status:204}}
      if(url.endsWith('/capabilities')){assert.notEqual(fault,'success','prepared session must not renegotiate capabilities');body={nativePlayback:1};}
      else if(url.endsWith('/mode')){assert.notEqual(fault,'success','prepared mode is already committed');selected=true;body={mode:'native'}}
      else if(url.endsWith('/control')){commands.push(JSON.parse(init.body));if(fault==='hung-control')return new Promise(()=>{});body={revision:10};}
      else if(url.endsWith('/activate')){if(fault==='cancel-pending'){queueMicrotask(()=>dispose());return new Promise(()=>{});}activated=true;body={activated:true}}
      else if(url.endsWith('/status')){
        if(selected&&fault==='hung')return new Promise(()=>{});
        body={state:'complete',source:{video:{contentType:'video/mp4; codecs="hvc1.1"'}},
          native:selected?{state:'ready',outputReady:fault!=='frame',visible:fault!=='visible',
            revision:fault==='revision'?0:10,width:1920,height:1080,time:0,duration:90}:null};
      }
      return {ok:true,status:200,json:async()=>body};
    }};
  vm.createContext(context);vm.runInContext(source,context);
  const dispose=context.desktopNativePlayback(media,'http://127.0.0.1',0,{onReady(){if(fault==='success')assert(activated,'ready is announced after the activation ACK');},onError(){errors++}},prep);
  for(let n=0;n<80&&!errors&&!activated;n++){await tick();await new Promise(r=>setTimeout(r,1))}
  if(fault==='cancel-pending'){dispose();await tick();assert.equal(errors,0);assert(finished>0,'cancelled adoption releases retained old picture');assert.equal(released,1);}
  else if(fault==='success'){
    assert(activated);assert.equal(errors,0);assert.equal(released,0);assert(finished>0);
    assert.equal(commands[0].visible,true);
    assert.equal(commands[0].paused,false,'first visible command must start playback without a second debounced flush');
    assert.equal(commands[0].rate,2);assert.equal(commands[0].volume,.4);assert.equal(commands[0].muted,false);
    media.currentTime=89.8;media.pause();scheduled.length=0;
    await new Promise(r=>setTimeout(r,5));await tick();
    assert(!scheduled.includes(40),'paused tail must retain normal polling rate');
  }
  else if(fault==='copy-fallback'){assert(activated);assert.equal(errors,0);assert.equal(released,0)}
  else {assert.equal(errors,1,fault+' must report bounded activation failure');
    assert.equal(released,1);assert(finished>0&&cancelled>0);}
  dispose();for(const timer of timers)clearTimeout(timer);
}
(async()=>{for(const fault of ['visible','frame','revision','hung','hung-control','success','copy-fallback','cancel-pending'])await scenario(fault);
  console.log('PASS: native visible/frame/revision and hanging-status ACK failures release and report error');
})().catch(error=>{console.error(error);process.exitCode=1});
