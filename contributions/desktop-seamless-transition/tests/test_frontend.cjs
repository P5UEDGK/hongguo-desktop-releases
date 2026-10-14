const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(require('node:path').join(__dirname,'../src/frontend-seamless.js'),'utf8');
// Flush both promise work and the simulated 1 ms session polling timers.
const tick=async()=>{for(let i=0;i<15;i++)await new Promise(resolve=>setTimeout(resolve,1))};
class Video extends EventTarget {
  constructor(){super();Object.assign(this,{paused:true,currentTime:0,playbackRate:1,volume:1,muted:false,
    duration:90,readyState:2,videoWidth:1920,videoHeight:1080,buffered:{length:1,start:()=>0,end:()=>9},style:{},removed:false});}
  play(){this.paused=false;this.dispatchEvent(new Event('playing'));return Promise.resolve();}
  pause(){this.paused=true;this.dispatchEvent(new Event('pause'));}
  remove(){this.removed=true;}
  requestVideoFrameCallback(fn){queueMicrotask(fn);}
  closest(){return this.stage;}
  getBoundingClientRect(){return {left:10,top:10,width:800,height:500};}
}
async function scenario(native,fail=false,fault=null){
  const calls=[],children=[],timers=new Set();let selected=false,revision=0,released=0,stopped=0,started=0;
  let confirmActivation,controllerId="c".repeat(32),now=0,expire,activationBudget,acceptanceCallback;
  const activated=new Promise(resolve=>confirmActivation=resolve);
  const current=new Video();current.volume=.3;current.playbackRate=3;current.paused=false;
  current.desktopSessionId=()=> 'a'.repeat(32);current.stage={append:v=>{v.stage=current.stage;children.push(v);}};
  const endpoint={origin:'http://127.0.0.1:23456',url:'http://127.0.0.1:23456/desktop/hls?series_id=1234567890123456&ep=2',key:'b'.repeat(64)};
  const context={URL,Event,Number,Math,Date:{now:()=>now},WeakMap,Proxy,Map,AbortController,window:{devicePixelRatio:1},
    w0:()=>endpoint,ik(){},desktopSupportsSource:async()=>true,
    setTimeout(fn,ms){if(ms===90000)expire=fn;if(ms>=15000&&!fault?.startsWith('hung'))return 999;if(ms<=2000&&ms>100){activationBudget=ms;if(fault!=='activation-timeout')return 998;}const id=setTimeout(()=>{if(fault==='activation-timeout'&&ms>100)now+=ms;if(fault==='no-frame'&&ms===100)now=90001;fn();},1);timers.add(id);return id;},
    clearTimeout:id=>{timers.delete(id);clearTimeout(id);},requestAnimationFrame:fn=>queueMicrotask(fn),
    document:{createElement:()=>new Video()},
    desktopCodecHls(video,url,start,callbacks,prep,windowed,state){
      callbacks={...callbacks}; // Production codec copies/enumerates callback keys.
      acceptanceCallback=callbacks.onAcceptanceHlsTransition;
      assert.equal(state.paused,true);assert(video.paused&&video.muted&&video.volume===0);
      queueMicrotask(()=>{callbacks.onAcceptanceHlsTransition({from:'copy',to:'h264'},7);callbacks.onTimeline(90,9);callbacks.onPlayableRange([0,9]);callbacks.onComplete(true);callbacks.onWindowOrigin(0);if(fault!=='no-frame')callbacks.onReady();});
      return Object.assign(()=>{stopped++;},{seek:value=>{video.currentTime=value;},sessionId:()=>controllerId});
    },
    fetch:async(url,init={})=>{
      url=String(url);calls.push({url,...init});let body={};
      if(init.method==='DELETE'){released++;return {ok:true,status:204};}
      if(url.endsWith('/activate')){await activated;if(fault==='activate')throw Error('activation rejected');}
      if(url.endsWith('/status')&&fault==='hung-status')return new Promise(()=>{});
      if(url.endsWith('/capabilities'))body={standbyPlayback:1,nativePlayback:native?1:0};
      else if(url.endsWith('/mode')){selected=true;body=JSON.parse(init.body);}
      else if(url.endsWith('/control')){revision++;body={revision};}
      else if(init.method==='POST'&&!url.endsWith('/activate'))body={id:'c'.repeat(32)};
      else if(url.endsWith('/status'))body=fail?{state:'failed'}:{state:'complete',
        source:{copyEligible:true,video:{contentType:'video/mp4; codecs="hvc1.1.6.L120.B0"'},audio:[]},
        native:selected?{outputReady:true,revision}:null};
      return {ok:true,status:200,json:async()=>url.endsWith('/status')&&fault==='hung-json'?new Promise(()=>{}):body};
    }};
  vm.createContext(context);vm.runInContext(source,context);
  assert.equal(context.desktopShouldPrewarm({duration:100,currentTime:70,playbackRate:1,readyState:4}),false);
  assert.equal(context.desktopShouldPrewarm({duration:100,currentTime:70,playbackRate:3,readyState:4}),true);
  assert.equal(context.desktopShouldPrewarm({duration:100,currentTime:70,playbackRate:3,readyState:4,desktopBuffering:true}),false);
  assert.equal(context.desktopShouldPrewarm({duration:4,desktopTimelineDuration:90,currentTime:2,playbackRate:1,readyState:4}),false);
  assert.equal(context.desktopShouldPrewarm({duration:10,desktopTimelineDuration:90,desktopTimeOrigin:80,currentTime:2,playbackRate:1,readyState:4}),true);
  const prep=context.desktopPrepareNext(endpoint.url,current);
  if(fault==='late-claim'||fault==='idle-expiry'){
    await tick();now=90001;if(fault==='idle-expiry')expire();
    const record=await prep.claimRecord(endpoint.url,0);await tick();
    assert.equal(record,null);assert.equal(released,1);if(!native)assert(children[0].removed);
    for(const timer of timers)clearTimeout(timer);return;
  }
  const record=await prep.claimRecord(endpoint.url,0);
  if(fail||fault==='no-frame'||fault?.startsWith('hung')){assert.equal(record,null);await tick();assert.equal(released,1);for(const timer of timers)clearTimeout(timer);return;}
  assert(record);assert.equal(record.settings.volume,.3);assert.equal(record.settings.rate,3);
  const create=calls.find(c=>c.headers?.['x-desktop-prewarm-parent']);
  assert(create);assert.equal(create.headers['x-desktop-prewarm-parent'],'a'.repeat(32));
  prep.dispose();await tick();assert.equal(released,0,'claim transfers ownership');
  if(native){
    const command=JSON.parse(calls.find(c=>c.url.endsWith('/control')).body);
    assert(command.paused&&command.muted&&!command.visible);assert.equal(command.rate,3);
    record.dispose();await tick();assert.equal(released,1);
  }else{
    const media=new Video();media.stage=current.stage;let ended=0,errors=0,fallbacks=0;
    if(fault==='play')children[0].play=()=>Promise.reject(Error('play rejected'));
    media.addEventListener('ended',()=>ended++);
    prep.retain(()=>started++);
    let timeline;const acceptance=[];
    if(fault==='replacement-id')controllerId='d'.repeat(32);
    if(fault==='pending-id')controllerId=null;
    const dispose=record.adopt(media,{onReady:()=>started++,onError:()=>errors++,onComplete:v=>assert(v),onTimeline:d=>timeline=d,onAcceptanceHlsTransition:(...args)=>acceptance.push(args)},()=>{
      fallbacks++;assert.equal(media.currentTime,0);assert.equal(media.play,Video.prototype.play);
      assert(children[0].removed);assert.equal(media.desktopSessionId,undefined);
      assert.equal(started,1,'failed standby must retain the old picture until fallback is ready');
      prep.finishRetained();assert.equal(started,2,'fallback readiness releases the retained picture');
    });
    controllerId='d'.repeat(32);
    assert.equal(media.desktopSessionId(),controllerId,'adopted media follows replacement codec sessions');
    assert.equal(dispose.sessionId(),controllerId);
    assert.equal(timeline,90);
    assert.deepEqual(acceptance,[[{from:'copy',to:'h264'},7]],'preparation notification is replayed exactly once with all arguments');
    acceptanceCallback({from:'h264',to:'retry'},8);
    assert.deepEqual(acceptance,[[{from:'copy',to:'h264'},7],[{from:'h264',to:'retry'},8]],'live callbacks remain forwarded once');
    assert.equal(media.volume,.3);assert.equal(media.playbackRate,3);assert.equal(media.paused,true);
    assert.equal(children[0].currentTime,0);assert.equal(children[0].style.opacity,'1');
    children[0].dispatchEvent(new Event('ended'));assert.equal(ended,1);
    dispose.seek(7);assert.equal(media.currentTime,7);
    if(fault==='activation-timeout'){
      await tick();assert.equal(fallbacks,1);assert.equal(stopped,1);assert.equal(released,1);
      assert(activationBudget>0&&activationBudget<=2000,'activation uses the remaining handoff deadline');
      dispose();for(const timer of timers)clearTimeout(timer);return;
    }
    await tick();assert.equal(media.paused,true);assert.equal(started,1,'retain old picture until activation is acknowledged');
    if(fault==='replacement-id'||fault==='pending-id')assert(calls.some(c=>c.url.endsWith('/'+'d'.repeat(32)+'/activate')));
    media.playbackRate=2;media.volume=.6;media.muted=true;
    if(fault==='pause-activation')media.pause();
    if(fault&&fault!=='replacement-id'&&fault!=='pending-id'&&fault!=='pause-activation'){
      if(fault==='cancel')dispose();
      confirmActivation();await tick();
      assert.equal(errors,0);assert.equal(fallbacks,fault==='cancel'?0:1);
      assert.equal(stopped,1);assert.equal(released,1);assert(children[0].removed);
      assert.equal(media.playbackRate,2);assert.equal(media.volume,.6);assert.equal(media.muted,true);
      const before=ended;children[0].dispatchEvent(new Event('ended'));assert.equal(ended,before);
      dispose();for(const timer of timers)clearTimeout(timer);return;
    }
    confirmActivation();await tick();assert.equal(media.paused,fault==='pause-activation');assert(started>=2);
    assert(calls.filter(c=>c.url.endsWith('/activate')).at(-1).url.endsWith('/'+controllerId+'/activate'),'activation follows a session replaced during POST');
    assert(activationBudget>0&&activationBudget<=2000);
    dispose();await tick();assert.equal(stopped,1);assert.equal(released,1);
    assert(children[0].removed);assert(!Object.hasOwn(media,'currentTime')||media.currentTime===0);
    assert.equal(media.playbackRate,2);assert.equal(media.volume,.6);assert.equal(media.muted,true);
  }
  for(const timer of timers)clearTimeout(timer);
}
(async()=>{await scenario(true);await scenario(false);await scenario(true,true);await scenario(false,true);
  for(const fault of ['activate','play','cancel','hung-status','hung-json','late-claim','idle-expiry','replacement-id','pending-id','no-frame','activation-timeout','pause-activation'])await scenario(false,false,fault);
  console.log('PASS: activation/play rollback and normal fallback, stale cancel suppression, bounded hanging fetch/JSON');
  console.log('PASS: cold-source request, speed threshold, hidden/muted first frame, ownership, HLS bridge, controls, failure and release');
})().catch(error=>{console.error(error);process.exitCode=1});
