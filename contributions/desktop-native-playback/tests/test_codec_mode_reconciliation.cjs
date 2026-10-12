const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(process.argv[2] || path.join(__dirname,'../src/frontend-codec.js'),'utf8');
(async()=>{for(const fault of ['lost-copy','stalled-copy','conflict-copy','lost-h264']){
 let selected=null,posts=0,statuses=0;const timers=new Set();
 const reply=body=>({ok:true,status:200,json:async()=>body,clone(){return reply(body);}});
 const context={URL,Headers,AbortController,DOMException,Map,Set,Number,Math,console,
  MediaSource:{isTypeSupported:()=>true},navigator:{mediaCapabilities:{decodingInfo:async()=>({supported:true,smooth:true})}},
  setTimeout(fn,ms){const id=setTimeout(fn,ms>=15000?5:ms);timers.add(id);return id;},clearTimeout(id){timers.delete(id);clearTimeout(id);},
  async fetch(url,init={}){
   if(String(url).endsWith('/mode')){posts++;selected=fault==='lost-h264'?'h264':'copy';if(fault==='stalled-copy')return new Promise(()=>{});if(fault==='conflict-copy')return {ok:false,status:409};throw TypeError('lost selection response');}
   statuses++;return reply({state:'complete',videoMode:selected,duration:90,startSeconds:0,source:{copyEligible:fault!=='lost-h264',video:{contentType:'video/mp4'},audio:[]}});
  }};
 vm.createContext(context);vm.runInContext(source,context);const transport=context.desktopCreateCodecFetch();
 await transport('http://127.0.0.1:1234/desktop/hls/'+'a'.repeat(32)+'/status');
 assert.equal(posts,1);assert.equal(transport.usedCopy(),fault!=='lost-h264','lost codec reply reconciles the committed copy/HLS state');assert(statuses>=2);
 transport.close();for(const t of timers)clearTimeout(t);
}console.log('PASS codec mode lost, stalled and conflicting response reconciliation');})().catch(e=>{console.error(e);process.exitCode=1;});
