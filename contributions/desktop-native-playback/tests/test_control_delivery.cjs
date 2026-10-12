const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[2]||path.join(__dirname,'../src/frontend-native.js'),'utf8');
const tick=async()=>{for(let n=0;n<20;n++)await new Promise(setImmediate);};
(async()=>{for(const fault of process.argv[3]?[process.argv[3]]:['lost','stalled','scroll']){
 let errors=0,ready=0,revision=0,selected=false,deletes=0,serial=0;const commands=[],timers=new Map(),listeners=new Map(),rect={left:10,top:20,width:800,height:600};
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
   if(url.endsWith('/status'))return reply({state:'complete',videoMode:selected?'native':null,duration:90,source:{video:{contentType:'video/mp4; codecs="hvc1.1"'}},native:selected?{state:'ready',outputReady:true,revision,width:800,height:600,duration:90,time:state.seek??0,...state}:null});
   return reply({id:'a'.repeat(32)});
  }};
 vm.createContext(context);vm.runInContext(source,context);const dispose=context.desktopNativePlayback(media,'http://127.0.0.1',0,{onReady(){ready++;},onError(){errors++;}},null);
 function run(predicate){for(const [id,timer] of [...timers])if(predicate(timer)){timers.delete(id);timer.fn();}}
 await tick();run(t=>t.fn.name==='flush');await tick();
 if(fault==='stalled'){run(t=>t.delay>=15000);await tick();}
 for(let n=0;n<10&&commands.length<2&&fault!=='scroll'&&!errors;n++){run(t=>t.delay<=100);await tick();}
 assert.equal(errors,0,'lost or timed-out accepted native control remains healthy');assert.equal(deletes,0);assert(ready);
 if(fault==='scroll'){
  const listener=listeners.get('scroll');assert(listener?.capture===true,'nested scrolling is observed in capture phase');
  rect.left=-30;rect.top=-20;listener.fn({target:{}});run(t=>t.fn.name==='flush');await tick();
  assert.deepEqual(commands.at(-1).rect,[-30,-20,800,516],'scroll moves the native child without resize or a later poll');
 }else{assert.equal(commands.length,2);if(fault==='stalled')assert.equal(commands.at(-1).seek,12,'new seek intent supersedes the timed-out absolute command');}
 dispose();await tick();assert(!listeners.has('scroll'),'scroll listener is removed with the owned player');timers.clear();
}console.log('PASS native accepted control loss/timeout recovery and nested scroll geometry cleanup');})().catch(e=>{console.error(e);process.exitCode=1;});
