const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[2],'utf8');
const tick=async()=>{for(let n=0;n<30;n++)await new Promise(setImmediate)};
async function scenario(fault){
  let standbyPosition=0;let now=0,errors=0,released=0,finished=0,cancelled=0,selected=true,activated=false,modeAck=false,registrationPolls=0,pauseInjected=false;
  let hiddenTicks=0,hiddenControlPosts=0,coldPosition,lateSeekSamples=0;
  const timers=new Set(),scheduled=[],commands=[],requests=[];
  const media=new EventTarget();Object.assign(media,{playbackRate:2,volume:.4,muted:false,paused:false,pause(){this.paused=true;},play(){this.paused=false;return Promise.resolve();},
    closest:()=>({classList:{add(){},remove(){}},querySelector:()=>({getBoundingClientRect:()=>({top:536,height:64})})}),
    getBoundingClientRect:()=>({left:0,top:0,width:800,height:600})});
  if(fault==='resume-seek-fallback')Object.assign(media,{playbackRate:1,volume:1,muted:false});
  const prep={settings:['resume-seek-fallback','invalid-resume','invalid-resume-new-seek','copy-fallback'].includes(fault)?{rate:3,volume:.2,muted:true}:{rate:2,volume:.4,muted:false},resumeInvalid:['invalid-resume','invalid-resume-new-seek'].includes(fault),resumeFailed:['resume-seek-fallback','invalid-resume','invalid-resume-new-seek'].includes(fault),resumePosition:['invalid-resume','invalid-resume-new-seek'].includes(fault)?0:30,claimRecord:async()=>{if(['pending-native-seek','invalid-resume-new-seek'].includes(fault)){await tick();dispose.seek(20);}return (fault==='settings-during-claim'&&Object.assign(media,{playbackRate:4,volume:.7,muted:true}),fault==='pause-during-claim'&&(pauseInjected=true,media.pause()),['cold-registration','resume-seek-fallback','invalid-resume','invalid-resume-new-seek','cold-hls-error'].includes(fault)?null:fault==='copy-fallback'?{mode:'copy',settings:{rate:3,volume:.2,muted:true},
      adopt(target,handlers,onFailure){
        assert.equal(target.playbackRate,3);assert.equal(target.volume,.2);assert.equal(target.muted,true);
        queueMicrotask(onFailure);return ()=>{};
      }}:{settings:fault==='settings-during-claim'?{rate:2,volume:.4,muted:false}:undefined,id:'a'.repeat(32),mode:'native',expiresAt:fault==='original-expiry'?1000:90000,source:{video:{contentType:'video/mp4; codecs="hvc1.1"'}},async seek(position){assert.equal(position,20);assert.equal(commands.length,0,'native pending seek is ACKed while hidden');await tick();standbyPosition=position;},dispose(){}});},dispose(){},
    finishRetained(){if(fault==='late-seek-during-activate'){assert(lateSeekSamples>=3,'late native seek must land before predecessor release');assert.equal(standbyPosition,20);}if(fault==='success')assert(activated,'old picture retained until activate ACK');if(fault==='pause-during-activate')assert.equal(commands.at(-1).paused,true,'in-flight pause is ACKed before old picture release');finished++},cancelClaim(){cancelled++}};
  const documentListeners=new Map();
  const context={URL,Event,Number,Math,Map,AbortController,window:{devicePixelRatio:1},
    Date:{now:()=>now},ResizeObserver:class{observe(){}disconnect(){}},
    document:{hidden:['hidden-surface','original-expiry'].includes(fault),head:{append(){}},createElement:()=>({remove(){}}),addEventListener(name,fn){documentListeners.set(name,fn);},removeEventListener(name){documentListeners.delete(name);}},
    setTimeout(fn,delay){scheduled.push(delay);if(delay>=15000||(fault==='cancel-pending'&&delay>10000))return 999;const id=setTimeout(()=>{now+=250;if(fault==='hidden-surface'&&now>=5000)context.document.hidden=false;if(fault==='hidden-before-activate'&&context.document.hidden&&delay===100&&++hiddenTicks>=20)context.document.hidden=false;fn()},1);timers.add(id);return id;},
    clearTimeout:id=>{timers.delete(id);clearTimeout(id)},
    w0:()=>({origin:'http://127.0.0.1',url:'http://127.0.0.1/desktop/hls?ep=2',key:'test'}),
    desktopCodecHls(target,url,position,handlers,preparation){coldPosition=position;
      assert(['copy-fallback','resume-seek-fallback','invalid-resume','invalid-resume-new-seek','cold-hls-error'].includes(fault));
      if(fault==='cold-hls-error'){queueMicrotask(()=>handlers.onError());return ()=>{};}
      if(fault==='copy-fallback'){assert.equal(target.playbackRate,3);assert.equal(target.volume,.2);assert.equal(target.muted,true);}
      else {assert.equal(position,fault==='invalid-resume-new-seek'?20:['invalid-resume','invalid-resume-new-seek'].includes(fault)?0:30);assert.equal(preparation,prep);assert.equal(target.playbackRate,3);assert.equal(target.volume,.2);assert.equal(target.muted,true);}
      activated=true;
      return ()=>{};
    },
    fetch:async(url,init={})=>{
      let body={};url=String(url);
      requests.push(url);
      if(init.method==='DELETE'){released++;return {ok:true,status:204}}
      if(url.endsWith('/capabilities')){assert.notEqual(fault,'success','prepared session must not renegotiate capabilities');body={nativePlayback:fault==='cold-hls-error'?0:1};}
      else if(url.endsWith('/mode')){assert.notEqual(fault,'success','prepared mode is already committed');selected=true;modeAck=true;body={mode:'native'}}
      else if(url.endsWith('/control')){if(context.document.hidden)hiddenControlPosts++;if(fault==='cold-registration')assert(registrationPolls>=2,'no controls before native registration');commands.push(JSON.parse(init.body));if(fault==='rejected-control')return {ok:false,status:429};if(fault==='hung-control')return new Promise(()=>{});if(fault==='pause-during-flush'&&!pauseInjected){pauseInjected=true;media.pause();}body={revision:10+commands.length};}
      else if(url.endsWith('/activate')){if(fault==='late-seek-during-activate')dispose.seek(20);if(fault==='pending-native-seek')assert.equal(standbyPosition,20,'pending native seek precedes activation');if(fault==='hidden-during-activate'){context.document.hidden=true;documentListeners.get('visibilitychange')?.();}if(fault==='cancel-pending'){queueMicrotask(()=>dispose());return new Promise(()=>{});}if(fault==='pause-during-activate'){pauseInjected=true;media.pause();}else if(fault.startsWith('pause-during-'))assert.equal(commands.at(-1).paused,true,'queued pause must be applied before activation');activated=true;body={activated:true}}
      else if(url.endsWith('/status')){
        if(fault==='hidden-before-activate'&&commands.length&&!pauseInjected){pauseInjected=true;context.document.hidden=true;documentListeners.get('visibilitychange')?.();}
        if(fault==='pause-during-status'&&commands.length&&!pauseInjected){pauseInjected=true;media.pause();}
        if(selected&&fault==='hung')return new Promise(()=>{});
        body={state:'complete',source:{video:{contentType:'video/mp4; codecs="hvc1.1"'}},
          native:selected?{state:'ready',outputReady:fault!=='frame',visible:fault!=='visible'&&!context.document.hidden,
            paused:[...commands].reverse().find(c=>'paused' in c)?.paused ?? false, revision:fault==='revision'?0:10+commands.length,width:1920,height:1080,time:standbyPosition,duration:90}:null};
        if(fault==='late-seek-during-activate'&&activated&&commands.some(c=>'seek'in c)){lateSeekSamples++;body.native.seeking=lateSeekSamples<3;body.native.time=lateSeekSamples<3?0:20;if(lateSeekSamples>=3)standbyPosition=20;}
        if(fault==='cold-registration'&&modeAck&&++registrationPolls===1)body.native={state:'preparing'};
      }
      else if(init.method==='POST')body={id:'a'.repeat(32)};
      return {ok:true,status:200,json:async()=>body};
    }};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../src/frontend-seamless.js'),'utf8'),context);
  vm.runInContext(source,context);
  const dispose=context.desktopNativePlayback(media,'http://127.0.0.1',['invalid-resume','invalid-resume-new-seek'].includes(fault)?90:fault==='resume-seek-fallback'?30:0,{onReady(){if(fault==='success')assert(activated,'ready is announced after the activation ACK');if(fault==='cold-registration')activated=true;},onError(){errors++}},prep);
  for(let n=0;n<80&&!errors&&!activated;n++){await tick();await new Promise(r=>setTimeout(r,1))}
  if(fault==='cancel-pending'){dispose();await tick();assert.equal(errors,0);assert(finished>0,'cancelled adoption releases retained old picture');assert.equal(released,1);}
  else if(fault==='cold-hls-error'){assert.equal(errors,1);assert(finished>0,'terminal cold HLS error releases old picture immediately');}
  else if(fault==='hidden-during-activate'){
    for(let n=0;n<10;n++){await tick();await new Promise(r=>setTimeout(r,1));}
    assert(activated);assert.equal(errors,0);assert.equal(finished,0,'hidden activation retains the old picture until visible');
    assert.equal(commands.at(-1).paused,true,'hidden in-flight activation must pause audio');
    context.document.hidden=false;documentListeners.get('visibilitychange')?.();
    for(let n=0;n<10;n++){await tick();await new Promise(r=>setTimeout(r,1));}
    assert.equal(errors,0);assert(finished>0,'showing the activated surface finishes retention');assert.equal(commands.at(-1).paused,false,'show restores the preserved playing intent after parked status polls');
  }
  else if(fault==='late-seek-during-activate'){for(let n=0;n<15;n++){await tick();await new Promise(r=>setTimeout(r,1));}assert(activated);assert.equal(errors,0);assert(finished>0);assert(lateSeekSamples>=3);}
  else if(fault==='pending-native-seek'){assert(activated);assert.equal(errors,0);assert.equal(standbyPosition,20);}
  else if(fault==='settings-during-claim'){assert(activated);assert.equal(errors,0);assert.equal(commands[0].rate,4);assert.equal(commands[0].volume,.7);assert.equal(commands[0].muted,true);}
  else if(fault==='success'){
    assert(activated);assert.equal(errors,0);assert.equal(released,0);assert(finished>0);
    assert.equal(commands[0].visible,true);
    assert.deepEqual(commands[0].rect,[0,0,800,536],'activation shares the prewarm chrome geometry');
    assert.equal(commands[0].paused,false,'first visible command must start playback without a second debounced flush');
    assert.equal(commands[0].rate,2);assert.equal(commands[0].volume,.4);assert.equal(commands[0].muted,false);
    media.currentTime=89.8;media.pause();scheduled.length=0;
    await new Promise(r=>setTimeout(r,5));await tick();
    assert(!scheduled.includes(40),'paused tail must retain normal polling rate');
  }
  else if(['copy-fallback','resume-seek-fallback','invalid-resume','invalid-resume-new-seek','hidden-surface','hidden-before-activate'].includes(fault)){assert(activated,JSON.stringify({fault,coldPosition,errors,rate:media.playbackRate,volume:media.volume,muted:media.muted}));assert.equal(errors,0);assert.equal(released,0)}
  else if(fault.startsWith('pause-during-')){assert(activated,'pause race must still activate');assert(pauseInjected);assert.equal(errors,0);assert.equal(media.paused,true);assert.equal(commands.at(-1).paused,true);}
  else if(fault==='cold-registration'){await new Promise(r=>setTimeout(r,5));await tick();assert(activated);assert.equal(errors,0);assert(registrationPolls>=2);assert(commands.length>0);assert(finished>0,'cold native readiness releases retained old picture');}
  else {assert.equal(errors,1,fault+' must report bounded activation failure');
    assert.equal(released,1);assert(finished>0&&cancelled>0);}
  if(fault==='original-expiry')assert(now<=1250,'claim cannot renew the original preparation deadline');
  if(fault==='rejected-control'){await tick();assert(!requests.some(url=>url.includes('/null/')),'terminal flush failure must not poll a null session');assert.equal(errors,1);assert.equal(activated,false);}
  if(fault==='hidden-before-activate')assert(hiddenControlPosts<=3,'hidden standby waits do not repeatedly POST an acknowledged pause');
  dispose();for(const timer of timers)clearTimeout(timer);
}
(async()=>{for(const fault of (process.argv[3]?[process.argv[3]]:[ 'late-seek-during-activate','pending-native-seek','hidden-before-activate','hidden-during-activate','settings-during-claim','rejected-control','original-expiry','hidden-surface','invalid-resume','invalid-resume-new-seek','visible','frame','revision','hung','hung-control','success','copy-fallback','cancel-pending','cold-registration','pause-during-flush','pause-during-status','pause-during-claim','pause-during-activate','resume-seek-fallback','cold-hls-error']))await scenario(fault);
  console.log('PASS: native visible/frame/revision and hanging-status ACK failures release and report error');
})().catch(error=>{console.error(error);process.exit(1)});
