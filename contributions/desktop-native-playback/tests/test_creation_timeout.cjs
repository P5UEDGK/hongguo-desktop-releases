const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
(async()=>{
 for(const supported of [false,true]) for(const cancel of [false,true]){
  let token=0,errors=0,postSignal,creation,cancelled=[];const timers=new Map();
  const media=new EventTarget();Object.assign(media,{playbackRate:1,volume:1,muted:false,closest:()=>null,getBoundingClientRect:()=>({left:0,top:0,width:800,height:600}),pause(){},play(){return Promise.resolve();}});
  const c={URL,Number,Math,Date,Event,AbortController,DOMException,queueMicrotask,crypto:require('node:crypto').webcrypto,
   ResizeObserver:class{observe(){}disconnect(){}},window:{},document:{hidden:false,addEventListener(){},removeEventListener(){}},
   setTimeout(fn,delay){timers.set(++token,{fn,delay});return token;},clearTimeout:id=>timers.delete(id),
   w0:()=>({origin:'http://127.0.0.1',url:'http://127.0.0.1/desktop/hls?ep=1',key:'owned'}),
   fetch:async(url,init={})=>{
    if(init.method==='POST'){postSignal=init.signal;creation=new URL(url).searchParams.get('request_token');return new Promise(()=>{});}
    if(init.method==='DELETE'){cancelled.push(String(url));return {ok:true,status:204};}
    return {ok:true,status:200,json:async()=>({nativePlayback:1,requestCancellation:supported?1:0})};
   }};
  vm.createContext(c);vm.runInContext(fs.readFileSync(process.argv[2]||path.join(__dirname,'../src/frontend-native.js'),'utf8'),c);
  const dispose=c.desktopNativePlayback(media,'http://127.0.0.1',0,{onError(){errors++;}},null,true);
  for(let n=0;n<20;n++)await new Promise(setImmediate);
  assert(postSignal,'initial creation POST must be cancellable');
  if(cancel)dispose();else [...timers.values()].find(t=>t.delay===15000).fn();
  for(let n=0;n<20;n++)await new Promise(setImmediate);
  assert(postSignal.aborted);if(supported){assert.match(creation,/^[0-9]{13}-[0-9a-f]{32}$/);assert(cancelled.some(url=>url.endsWith('/requests/'+creation)),'lost creation response is cancelled by token');}assert.equal(errors,cancel?0:1,'stalled creation must settle through error or dispose');dispose();assert.equal(timers.size,0);
 }
 console.log('PASS initial creation timeout and disposal abort stalled POST');
})().catch(e=>{console.error(e);process.exitCode=1;});
