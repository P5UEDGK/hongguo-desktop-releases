// Run against #204 after #207 and this package's patches, with no media/provider access.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[2],'utf8');
const settle=async()=>{for(let n=0;n<20;n++)await new Promise(setImmediate);};
(async()=>{
  const commands=[],timers=new Map(),observed=[],listeners=new Map();let tick=0,selected=false;
  let chromeTop=450,revision=0,shown=true,panel=null,observer,overlayDisposed=false;
  const chromeListeners=new Map();
  const chrome={getBoundingClientRect:()=>({left:20,top:chromeTop,width:800,height:550-chromeTop}),
    matches:()=>shown,addEventListener:(n,fn)=>chromeListeners.set(n,fn),removeEventListener:n=>chromeListeners.delete(n)};
  const stage={classList:{add(){},remove(){}},querySelector:s=>s==='.player-chrome'?chrome:s==='.desktop-danmaku-panel'?panel:null};
  const media={playbackRate:1,volume:1,muted:false,closest:()=>stage,
    play:()=>Promise.resolve(),pause(){},dispatchEvent(){},
    addEventListener:(name,fn)=>listeners.set(name,fn),removeEventListener:name=>listeners.delete(name),
    getBoundingClientRect:()=>({left:20,top:50,width:800,height:500})};
  const context={desktopNativeControlsOverlay:()=>({ready:false,dispose(){overlayDisposed=true;}}),URL,Event,DOMException,Number,Math,Date,window:{devicePixelRatio:1.5},
    getComputedStyle:()=>({opacity:shown?'1':'0',display:'block',visibility:'visible'}),
    MutationObserver:class{constructor(fn){this.fn=fn;observer=this;}observe(){}disconnect(){observer=null;}},
    ResizeObserver:class{constructor(fn){this.fn=fn;context.resize=this;}observe(node){observed.push(node);}disconnect(){observed.length=0;}},
    document:{hidden:false,head:{append(){}},createElement:()=>({remove(){}}),addEventListener(){},removeEventListener(){}},
    setTimeout:(fn,delay)=>{timers.set(++tick,{fn,delay});return tick;},clearTimeout:id=>timers.delete(id),
    w0:()=>({origin:'http://127.0.0.1:4567',url:'http://127.0.0.1:4567/desktop/hls',key:'fixture'}),
    desktopCodecHls:()=>{throw Error('Unexpected fallback');},
    fetch:async(url,init={})=>{
      url=String(url);
      let body={state:'complete',source:{video:{contentType:'video/mp4; codecs="hvc1.1.6.L120.B0"'}}};
      if(url.endsWith('/capabilities'))body={nativePlayback:1};
      else if(url.endsWith('/mode')){selected=true;body={mode:'native'};}
      else if(url.endsWith('/control')){commands.push(JSON.parse(init.body));body={revision:++revision};}
      else if(init.method==='POST')body={id:'a'.repeat(32)};
      else if(selected)body.native={state:'ready',width:1920,height:1080,time:5,duration:90,revision,paused:false};
      return {ok:true,status:init.method==='DELETE'?204:200,json:async()=>body};
    }};
  vm.createContext(context);vm.runInContext(source,context);
  const stop=context.desktopNativePlayback(media,'http://127.0.0.1',0,{onReady(){}},null);
  await settle();
  assert.deepEqual(commands.find(c=>c.rect).rect,[30,75,1200,750],'full video height, including DPI');
  assert.deepEqual(commands.find(c=>c.rect).occlusion,[],'initial alpha controls never cut video while the first bitmap is preparing');
  assert(observed.includes(chrome),'control band height changes are observed');
  chromeTop=400;context.resize.fn();await settle();
  assert.deepEqual(commands.filter(c=>c.rect).at(-1).rect,[30,75,1200,750],'toolbar resize does not rescale video');
  assert.deepEqual(commands.filter(c=>c.rect).at(-1).occlusion,[]);
  shown=false;observer.fn();await settle();
  assert.deepEqual(commands.filter(c=>c.rect).at(-1).rect,[30,75,1200,750]);
  assert.deepEqual(commands.filter(c=>c.rect).at(-1).occlusion,[],'idle restores the complete video region');
  shown=true;panel={getBoundingClientRect:()=>({left:100,top:200,width:250,height:260})};
  observer.fn();await settle();
  assert.deepEqual(commands.filter(c=>c.rect).at(-1).occlusion,[120,225,375,390],
    'only the opaque settings panel needs a bounded cutout');
  async function flushControls(){
    for(const [id,entry] of [...timers])if(entry.delay===250){timers.delete(id);await entry.fn();}
    await settle();
  }
  media.pause();await flushControls();
  assert.equal(media.paused,true);assert.equal(commands.at(-1).paused,true);
  await media.play();await flushControls();
  assert.equal(media.paused,false);assert.equal(commands.at(-1).paused,false);
  assert(listeners.has('desktopsociallayout'));
  stop();assert(overlayDisposed,"native bitmap painter disposed");await settle();
  assert.equal(observed.length,0);assert.equal(listeners.size,0,'cleanup removes resize and social listeners');
  assert.equal(observer,null);assert.equal(chromeListeners.size,0,'cleanup removes control visibility observer and events');
  if(process.argv[3]){
    const standby=fs.readFileSync(process.argv[3],'utf8');vm.runInContext(standby,context);
    assert.deepEqual(Array.from(context.desktopNativeSurfaceRect(media)),[30,75,1200,750],
      'next episode prewarms at the same full video dimensions');
  }
  console.log('PASS full native video/DPI, overlay visibility/resize/settings, pause/resume and cleanup');
})().catch(error=>{console.error(error);process.exitCode=1;});
