const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[2]||path.join(__dirname,'../src/frontend-native.js'),'utf8');
const tick=async()=>{for(let n=0;n<20;n++)await new Promise(setImmediate);};
(async()=>{for(const fault of process.argv[3]?[process.argv[3]]:['status-lost','status-timeout','status-5xx','status-malformed','status-exhausted','status-404']){
 let inject=false,statusAttempts=0;let errors=0,ready=0,revision=0,selected=false,deletes=0,serial=0;const commands=[],timers=new Map(),listeners=new Map(),rect={left:10,top:20,width:800,height:600};
 const state={paused:false,rate:2,volume:.5,muted:false,visible:true};
 const stage={classList:{add(){},remove(){}},querySelector:()=>null};const media=new EventTarget();Object.assign(media,{playbackRate:2,volume:.5,muted:false,closest:()=>stage,getBoundingClientRect:()=>rect,pause(){},play(){return Promise.resolve();}});
 const reply=body=>({ok:true,status:200,json:async()=>body});
 const context={URL,Event,AbortController,Number,Math,Date,window:{devicePixelRatio:1},ResizeObserver:class{observe(){}disconnect(){}},
  document:{hidden:false,addEventListener(name,fn,capture){listeners.set(name,{fn,capture});},removeEventListener(name,fn,capture){const entry=listeners.get(name);if(entry?.fn===fn&&entry.capture===capture)listeners.delete(name);}},
  setTimeout(fn,delay){const id=++serial;timers.set(id,{fn,delay});return id;},clearTimeout:id=>timers.delete(id),
  w0:()=>({origin:'http://127.0.0.1',url:'http://127.0.0.1/desktop/hls?ep=1',key:'owned'}),
  desktopCodecHls(){throw Error('healthy native control cannot fall back');},
  async fetch(input,init={}){const url=String(input);
   if(init.method==='DELETE'){deletes++;return {ok:true,status:204};}
   if(url.endsWith('/capabilities'))return reply({nativePlayback:1});
   if(url.endsWith('/mode')){selected=true;return reply({mode:'native'});}
   if(url.endsWith('/control')){const command=JSON.parse(init.body);commands.push(command);Object.assign(state,command);revision++;
    if(commands.length===1&&fault==='lost')throw TypeError('accepted control response lost');
    if(commands.length===1&&fault==='stalled'){media.currentTime=12;return new Promise(()=>{});}
    return reply({revision});
   }
   if(url.endsWith('/status')&&inject){statusAttempts++;
    if(fault==='status-404')return {ok:false,status:404};
    if(statusAttempts===1||fault==='status-exhausted'){
     if(fault==='status-5xx')return {ok:false,status:503};
     if(fault==='status-malformed')return {ok:true,status:200,json:async()=>{throw SyntaxError('truncated JSON')}};
     if(fault==='status-timeout')return new Promise(()=>{});
     throw TypeError('lost status response');
    }
   }
   if(url.endsWith('/status'))return reply({state:'complete',videoMode:selected?'native':null,duration:90,source:{video:{contentType:'video/mp4; codecs="hvc1.1"'}},native:selected?{state:'ready',outputReady:true,revision,width:800,height:600,duration:90,time:state.seek??0,...state}:null});
   return reply({id:'a'.repeat(32)});
  }};
 vm.createContext(context);vm.runInContext(source,context);const dispose=context.desktopNativePlayback(media,'http://127.0.0.1',0,{onReady(){ready++;},onError(){errors++;}},null);
 function run(predicate){for(const [id,timer] of [...timers])if(predicate(timer)){timers.delete(id);timer.fn();}}
 await tick();run(t=>t.fn.name==='flush');await tick();
 if(fault==='stalled'){run(t=>t.delay>=15000);await tick();}
 for(let n=0;n<10&&commands.length<2&&fault!=='scroll'&&!errors;n++){run(t=>t.delay<=100);await tick();}
 assert.equal(errors,0,'lost or timed-out accepted native control remains healthy');assert.equal(deletes,0);assert(ready);
 inject=true;run(t=>t.delay===250);await tick();if(fault==='status-timeout'){run(t=>t.delay>=15000);await tick();}
 if(fault!=='status-404'){assert.equal(errors,0,'single transient native status failure preserves playback');assert.equal(deletes,0);}
 for(let n=0;n<4;n++){run(t=>t.delay===250);await tick();}
 if(['status-404','status-exhausted'].includes(fault)){assert.equal(errors,1,'fatal or exhausted failures terminate');assert.equal(deletes,1);}
 else{assert(statusAttempts>=2);assert.equal(errors,0);assert.equal(deletes,0);assert.equal(ready,1);}
 dispose();await tick();assert(!listeners.has('scroll'),'scroll listener is removed with the owned player');timers.clear();
}console.log('PASS native status transient faults recover and fatal/exhausted budgets terminate');})().catch(e=>{console.error(e);process.exitCode=1;});
