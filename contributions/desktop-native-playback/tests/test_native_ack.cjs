const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const tick=()=>new Promise(setImmediate);
async function scenario(hostContext, invalidResume = false){
  let selected=false,revision=0,position=0,ready=0,seeked=0,token=0,allowReady=false;
  const calls=[],timers=new Map();
  const stage={classList:{add(){},remove(){}},querySelector:()=>null};
  const media=new EventTarget();Object.assign(media,{playbackRate:2,volume:.2,muted:true,closest:()=>stage,
    getBoundingClientRect:()=>({left:0,top:0,width:600,height:400}),pause(){},play(){return Promise.resolve();}});
  media.addEventListener('seeked',()=>seeked++);
  const hostCalls=[];
  const context={URL,Event,Number,Math,Date,AbortController,DOMException,console,
    window:{devicePixelRatio:1,...(hostContext?{__TAURI_INTERNALS__:{metadata:{currentWindow:{label:'owned-player'}},
      async invoke(name,args){hostCalls.push([name,args]);return name.endsWith('inner_position')?{x:-150,y:25}:{width:600,height:400};}}}:{})},
    ResizeObserver:class{observe(){}disconnect(){}},
    document:{hidden:false,addEventListener(){},removeEventListener(){}},
    setTimeout(fn,delay){timers.set(++token,{fn,delay});return token;},clearTimeout(id){timers.delete(id);},
    w0:()=>({origin:'http://127.0.0.1:1234',url:'http://127.0.0.1:1234/desktop/hls?series_id=12345678&ep=1',key:'fixture'}),
    desktopCodecHls(){throw Error('unexpected H264 fallback');},
    async fetch(url,init={}){
      url=String(url);calls.push([url,init]);let body;
      if(init.method==='DELETE')return {ok:true,status:204};
      if(url.endsWith('/capabilities'))body={nativePlayback:1};
      else if(url.endsWith('/mode')){selected=true;body={mode:'native'};}
      else if(url.endsWith('/control')){const command=JSON.parse(init.body);revision++;if('seek'in command)position=command.seek;body={revision};}
      else if(init.method==='POST')body={id:'a'.repeat(32)};
      else body={state:'complete',duration:90,source:{video:{contentType:'video/mp4; codecs="hvc1.1"'},audio:[]},
        native:selected?{state:allowReady?'ready':'preparing',outputReady:true,revision,
          width:allowReady?128:0,height:128,time:position,duration:90,paused:true,seeking:false}:null};
      return {ok:true,status:200,json:async()=>body};
    }};
  vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/frontend-native.js'),'utf8'),context);
  const dispose=context.desktopNativePlayback(media,'http://127.0.0.1',invalidResume?90:0,{onReady(){if(++ready===1)media.currentTime=25;}},null,true);
  await tick();
  if(invalidResume){
    const creates=calls.filter(([url,init])=>init.method==='POST'&&!url.endsWith('/mode')&&!url.endsWith('/control'));
    assert.equal(creates.length,2,'invalid EOF session is replaced before native mode');
    assert.equal(new URL(creates[0][0]).searchParams.get('start_seconds'),'90');
    assert.equal(new URL(creates[1][0]).searchParams.get('start_seconds'),null);
    assert(calls.some(([,init])=>init.method==='DELETE'));
  }
  const initial=[...timers].filter(([,entry])=>entry.delay===250);
  assert.equal(initial.length,2,'initial layout and first preparing poll are queued independently');
  allowReady=true;
  for(const [id,entry] of initial){timers.delete(id);await entry.fn();await tick();}
  assert.equal(ready,1);assert.equal(media.currentTime,25);
  assert.equal(seeked,0,'new seek cannot be acknowledged by the pre-callback revision');
  assert(!calls.some(([url,init])=>url.endsWith('/control')&&'seek'in JSON.parse(init.body)),'seek remains queued until its flush');
  // Poll before its new control flush: stale time must not replace the target.
  const poll=[...timers].filter(([,entry])=>entry.delay===250).at(-1);
  timers.delete(poll[0]);await poll[1].fn();await tick();
  assert.equal(media.currentTime,25);assert.equal(seeked,0);
  const pending=[...timers].filter(([,entry])=>entry.delay===250);
  for(const [id,entry] of pending){timers.delete(id);await entry.fn();await tick();}
  assert.equal(position,25);assert.equal(seeked,1);assert.equal(media.currentTime,25);
  if(hostContext){
    const mode=JSON.parse(calls.find(([url])=>url.endsWith('/mode'))[1].body);
    assert.deepEqual(mode.window,{rect:[-150,25,600,400]});
    assert.equal(hostCalls.length,2);assert(hostCalls.every(([,args])=>args.label==='owned-player'));
  }
  dispose();await tick();timers.clear();
}
(async()=>{await scenario(false);await scenario(true);await scenario(true,true);console.log('PASS: seek waits for its own sent revision; requesting Tauri window is bound; saved EOF recreates zero-origin before native selection');})().catch(error=>{console.error(error);process.exitCode=1});
