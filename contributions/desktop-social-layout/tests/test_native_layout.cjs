// Run against #204 after #207 and this package's patches, with no media/provider access.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[2],'utf8');
const settle=async()=>{for(let n=0;n<20;n++)await new Promise(setImmediate);};
(async()=>{
  const commands=[],timers=new Map(),observed=[],listeners=new Map();let tick=0,selected=false;
  let chromeTop=450,revision=0;
  const chrome={getBoundingClientRect:()=>({top:chromeTop,height:550-chromeTop})};
  const stage={classList:{add(){},remove(){}},querySelector:s=>s==='.player-chrome'?chrome:null};
  const media={playbackRate:1,volume:1,muted:false,closest:()=>stage,
    play:()=>Promise.resolve(),pause(){},dispatchEvent(){},
    addEventListener:(name,fn)=>listeners.set(name,fn),removeEventListener:name=>listeners.delete(name),
    getBoundingClientRect:()=>({left:20,top:50,width:800,height:500})};
  const context={URL,Event,DOMException,Number,Math,Date,window:{devicePixelRatio:1.5},
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
  assert.deepEqual(commands.find(c=>c.rect).rect,[30,75,1200,600],'native surface ends at actual control band, including DPI');
  assert(observed.includes(chrome),'control band height changes are observed');
  chromeTop=400;context.resize.fn();await settle();
  assert.deepEqual(commands.filter(c=>c.rect).at(-1).rect,[30,75,1200,525],'resized toolbar updates native geometry immediately');
  async function flushControls(){
    for(const [id,entry] of [...timers])if(entry.delay===250){timers.delete(id);await entry.fn();}
    await settle();
  }
  media.pause();await flushControls();
  assert.equal(media.paused,true);assert.equal(commands.at(-1).paused,true);
  await media.play();await flushControls();
  assert.equal(media.paused,false);assert.equal(commands.at(-1).paused,false);
  assert(listeners.has('desktopsociallayout'));
  stop();await settle();
  assert.equal(observed.length,0);assert.equal(listeners.size,0,'cleanup removes resize and social listeners');
  console.log('PASS native measured toolbar/DPI/resize, pause/resume commands and cleanup');
})().catch(error=>{console.error(error);process.exitCode=1;});
