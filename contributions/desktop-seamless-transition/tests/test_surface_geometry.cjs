const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../src/frontend-seamless.js'),'utf8');
async function verify(chromeTop,scale,expected){
  let placed=false,revision=0,resolveTimer,selected=false,nativeStatuses=0;const calls=[],pending=new Set();
  const media={playbackRate:2,volume:.4,muted:false,desktopSessionId:()=> 'a'.repeat(32),
    getBoundingClientRect:()=>({left:10,top:20,width:800,height:600}),
    closest:()=>({querySelector:()=>chromeTop===null?null:{getBoundingClientRect:()=>({top:chromeTop,height:64})}})};
  const context={URL,Number,Math,Date,Map,WeakMap,AbortController,window:{devicePixelRatio:scale},
    setTimeout(fn,ms){if(ms>=15000)return 999;const t=setTimeout(fn,1);pending.add(t);return t;},
    clearTimeout(t){clearTimeout(t);pending.delete(t);},w0:()=>({origin:'http://127.0.0.1',url:'http://127.0.0.1/desktop/hls?ep=2',key:'test'}),
    fetch:async(url,init={})=>{url=String(url);let body={};
      if(url.endsWith('/capabilities'))body={standbyPlayback:1,nativePlayback:1};
      else if(init.method==='POST'&&url.includes('?'))body={id:'b'.repeat(32)};
      else if(url.endsWith('/mode'))selected=true;
      else if(url.endsWith('/control')){assert(nativeStatuses>=2,'wait for registered native session, not placeholder status');calls.push(JSON.parse(init.body));placed=true;body={revision:++revision};}
      else if(url.endsWith('/status')){body={state:'ready',source:{video:{contentType:'video/mp4; codecs="hvc1.1"'}}};
        if(selected)body.native=++nativeStatuses===1?{state:'preparing'}:{state:'preparing',outputReady:placed,revision};}
      return {ok:true,status:init.method==='DELETE'?204:200,json:async()=>body};
    }};
  vm.createContext(context);vm.runInContext(source,context);
  const prep=context.desktopPrepareNext('http://127.0.0.1/desktop/hls?ep=2',media);
  try{
    const record=await Promise.race([prep.claimRecord('http://127.0.0.1/desktop/hls?ep=2',0),new Promise(r=>{resolveTimer=setTimeout(()=>r(null),200);})]);
    assert(record,'hidden layout must be applied before waiting for a frame');
    assert.deepEqual(calls[0].rect,expected,'prewarm uses actual chrome geometry and DPI');
    assert.equal(calls[0].visible,false);assert.equal(calls[0].paused,true);assert.equal(calls[0].muted,true);
    assert.deepEqual(Array.from(context.desktopNativeSurfaceRect(media)),expected);
    record.dispose();
  }finally{clearTimeout(resolveTimer);prep.cancelClaim();for(const t of pending)clearTimeout(t);}
}
(async()=>{await verify(556,1,[10,20,800,536]);await verify(556,1.5,[15,30,1200,804]);await verify(null,1,[10,20,800,516]);
 console.log('PASS: hidden layout precedes first frame; actual chrome, DPI and fallback geometry');
})().catch(e=>{console.error(e);process.exitCode=1});
