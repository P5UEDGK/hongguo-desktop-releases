const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../src/frontend-seamless.js'),'utf8');
const tick=()=>new Promise(setImmediate);
async function scenario(native,position,fault='',fallbackFrames=false){
  let now=0,claimed=false,selected=false,revision=0,target=0,statuses=0,released=0,retired=0,plays=0,activated=false;
  const calls=[],videos=[],timers=new Set(),frames=new Map();let frameId=0,codecCallbacks;
  class Video extends EventTarget{
    constructor(){super();Object.assign(this,{currentTime:fault==='advanced'?.051:0,duration:90,playbackRate:1,volume:0,muted:true,paused:true,seeking:false,readyState:2,videoWidth:128,videoHeight:128,style:{opacity:'0'}});if(fallbackFrames)this.requestVideoFrameCallback=undefined;}
    closest(){return this.stage;}
    getBoundingClientRect(){return {left:0,top:0,width:800,height:600};}
    pause(){this.paused=true;}
    play(){assert(activated,'no playback before activation');plays++;this.paused=false;return Promise.resolve();}
    remove(){this.removed=true;}
    requestVideoFrameCallback(fn){frames.set(++frameId,fn);return frameId;}
    cancelVideoFrameCallback(id){frames.delete(id);}
  }
  const current=new Video();current.volume=.4;current.playbackRate=2;current.desktopSessionId=()=> 'a'.repeat(32);
  if(fault==='pending-parent')current.desktopSessionId=()=>null;
  current.stage={append:v=>{v.stage=current.stage;videos.push(v);},querySelector:()=>null};
  const url='http://127.0.0.1/desktop/hls?ep=2';
  const c={URL,Event,Number,Math,Map,WeakMap,AbortController,Date:{now:()=>now},window:{devicePixelRatio:1},
    w0:()=>({origin:'http://127.0.0.1',url,key:'test'}),desktopSupportsSource:async()=>true,
    setTimeout(fn,ms){if(ms>=15000)return 999;const timer=setTimeout(()=>{now+=ms;fn();},0);timers.add(timer);return timer;},
    clearTimeout(t){timers.delete(t);clearTimeout(t);},requestAnimationFrame:fn=>queueMicrotask(fn),document:{createElement:()=>new Video()},
    desktopCodecHls(video,u,start,callbacks,preparation,windowed){
      assert.equal(windowed,['windowed','mode-mismatch'].includes(fault));
      assert.equal(start,0);codecCallbacks=callbacks;
      queueMicrotask(()=>{callbacks.onTimeline(fault==='unknown-duration'?Infinity:90,90);callbacks.onWindowOrigin(0);callbacks.onReady();});
      return Object.assign(()=>{}, {sessionId:()=> 'b'.repeat(32),activate:()=>{activated=true;},seek(value){
        assert(claimed,'no speculative seek');assert(video.paused&&video.muted&&video.style.opacity==='0');
        calls.push({seek:value});video.seeking=true;
        if(fault==='cancel'){queueMicrotask(()=>prep.cancelClaim());return;}
        if(fault==='seek-error')throw Error('seek rejected');
        if(fault==='timeout')return;
        queueMicrotask(()=>{video.currentTime=value;video.seeking=false;callbacks.onReady();video.dispatchEvent(new Event('seeked'));
          const pending=[...frames.values()];frames.clear();for(const fn of pending)fn(0,{mediaTime:value});});
      }});
    },
    fetch:async(input,init={})=>{
      const request=String(input);let body={};
      if(init.method==='DELETE'){released++;return {ok:true,status:204};}
      if(request.endsWith('/capabilities')){if(['parent-refresh','pending-parent'].includes(fault))current.desktopSessionId=()=> 'c'.repeat(32);body={standbyPlayback:1,nativePlayback:native?1:0};}
      else if(request.endsWith('/mode'))selected=true;
      else if(request.endsWith('/control')){
        const command=JSON.parse(init.body);calls.push(command);revision++;
        if('seek'in command){assert(claimed,'no speculative seek');assert(command.paused&&command.muted&&!command.visible);target=command.seek;
          if(fault==='seek-error')throw Error('seek rejected');
          if(fault==='cancel')queueMicrotask(()=>prep.cancelClaim());}
        body={revision};
      }else if(request.endsWith('/status')){
        const seeking=target>0&&++statuses===1;
        body={state:'complete',duration:fault==='unknown-duration'?null:90,source:{video:{contentType:'video/mp4; codecs="hvc1.1"'},audio:[]},
          native:selected?{state:'ready',outputReady:!(target&&fault==='timeout')&&!seeking,revision:seeking?revision-1:revision,
            time:fault==='advanced'? .051:seeking?0:target,duration:fault==='unknown-duration'?Infinity:90,paused:true,muted:true,visible:false,seeking}:null};
        if(fault.startsWith('prepare-failed')){body.state='failed';if(fault==='prepare-failed-unknown')delete body.duration;}
      }else if(request.endsWith('/activate')){activated=true;body={activated:true};}
      else if(init.method==='POST'){if(['parent-refresh','pending-parent'].includes(fault))assert.equal(init.headers['x-desktop-prewarm-parent'],'c'.repeat(32));body={id:'b'.repeat(32)};}
      return {ok:true,status:200,json:async()=>body};
    }};
  vm.createContext(c);vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),c);vm.runInContext(source,c);const prep=c.desktopPrepareNext(url,current,['windowed','mode-mismatch'].includes(fault));
  try{
    if(!fault.startsWith('prepare-failed'))for(let n=0;n<15;n++)await tick();
    assert.equal(plays,0);assert(!calls.some(x=>'seek'in x),'prewarm stays at the opening');
    if(videos[0]&&fault!=='advanced')assert(videos[0].paused&&videos[0].currentTime<=.05&&videos[0].style.opacity==='0');
    prep.retain(()=>retired++);claimed=true;
    if(fault==='unknown-duration'&&videos[0])videos[0].duration=Infinity;
    const record=await prep.claimRecord(fault==='identity'?url+'&other=1':url,position,fault==='windowed');
    if(fault&&!['windowed','parent-refresh','pending-parent','settings-live'].includes(fault)||!Number.isFinite(position)||position<0||position>=90){
      assert.equal(record,null,'unsafe/failed reuse must fall back');
      if(fault.startsWith('prepare-failed')){
        assert.equal(prep.resumeInvalid,fault!=='prepare-failed-unknown'&&position>=90);
        assert.equal(prep.resumePosition,fault==='prepare-failed-unknown'?null:position>=90?0:position,'failed preparation cannot bypass cold EOF validation without a known duration');
        assert.equal(retired,0);prep.finishRetained();assert.equal(retired,1);
      }
      else if(fault==='mode-mismatch'){assert.equal(retired,0,'mode mismatch keeps old picture for cold readiness');prep.finishRetained();assert.equal(retired,1);}
      else if(fault==='unknown-duration'){assert.equal(prep.resumeFailed,true);assert.equal(prep.resumePosition,null,'unknown duration cannot preserve an unvalidated cold resume');prep.finishRetained();}
      else if(['timeout','seek-error'].includes(fault)){assert.equal(prep.resumeFailed,true);assert.equal(prep.resumePosition,position);assert.equal(prep.settings.rate,2);assert.equal(prep.settings.volume,.4);assert.equal(prep.settings.muted,true);assert.equal(retired,0,'seek failure preserves old picture for ordinary loading');prep.finishRetained();assert.equal(retired,1);}
      else {
        if(!fault && (!Number.isFinite(position)||position<0||position>=90)){
          assert.equal(prep.resumeInvalid,true,'invalid saved progress is distinguished from a seek failure');
          assert.equal(prep.resumePosition,0,'cold fallback restarts invalid progress');
        }
        prep.cancelClaim();
      }
    }else{
      assert(record,'valid resume reuses the prepared session');assert.equal(plays,0);
      assert.equal(record.expiresAt,90000,'claim carries the original preparation expiry');
      assert.equal(record.id,'b'.repeat(32));assert.equal(record.settings.rate,2);
      if(position>.05){assert.equal(calls.filter(x=>'seek'in x).length,1);assert.equal(native?target:videos[0].currentTime,position);}
      else assert(!calls.some(x=>'seek'in x));
      if(!native){const media=new Video();media.stage=current.stage;Object.assign(media,{playbackRate:4,volume:.7,muted:false});const dispose=record.adopt(media,{onReady(){}});
        assert.equal(media.playbackRate,4);assert.equal(media.volume,.7);assert.equal(media.muted,false);
        for(let n=0;n<20;n++)await tick();assert.equal(media.currentTime,position>.05?position:0);assert.equal(videos.length,1);assert(activated);dispose();}
      else record.dispose();
    }
    for(let n=0;n<10;n++)await tick();assert.equal(released,1,'single session released once');
  }finally{prep.cancelClaim();for(const t of timers)clearTimeout(t);}
}
(async()=>{
  if(process.argv[3]){await scenario(process.argv[4]==='native',30,process.argv[3]);console.log('PASS selected standby case');return;}
  for(const native of [true,false]){
    for(const position of [30,90,91])await scenario(native,position,'prepare-failed');
    await scenario(native,90,'prepare-failed-unknown');
    for(const position of [0,.05,.051,30,89.8])await scenario(native,position);
    for(const position of [-1,NaN,Infinity,90,91])await scenario(native,position);
    for(const fault of ['identity','cancel','timeout','seek-error','unknown-duration','windowed','mode-mismatch','parent-refresh','pending-parent'])await scenario(native,30,fault);
  }
  await scenario(true,0,'advanced');
  await scenario(false,0,'advanced');
  await scenario(false,.051,'',true);await scenario(false,89.8,'',true);
  console.log('PASS: 48 native/HLS resume cases, including failed preparation with known/unknown duration, target-frame readiness, invalid positions, cancellation, timeout and retention');
})().catch(e=>{console.error(e);process.exitCode=1;});
