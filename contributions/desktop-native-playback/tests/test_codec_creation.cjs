const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto').webcrypto;
const source=fs.readFileSync(process.argv[2]||path.join(__dirname,'../src/frontend-codec.js'),'utf8');
const tick=async()=>{for(let n=0;n<20;n++)await new Promise(setImmediate);};
(async()=>{for(const fault of ['lost','abort','close']){
 const calls=[];let cancellation=null,entered;const started=new Promise(r=>entered=r);
 const context={URL,Headers,AbortController,DOMException,Date,Map,Set,Number,Math,crypto,console,setTimeout,clearTimeout,
  async fetch(input,init={}){const url=new URL(input);calls.push({url:url.href,method:init.method});
   if(init.method==='DELETE'){cancellation=url.pathname.split('/').at(-1);return {ok:true,status:204};}
   const token=url.searchParams.get('request_token');assert.match(token||'',/^\d{13}-[a-f0-9]{32}$/,'direct HLS creation has a cancellation token');entered();
   if(fault==='lost')throw TypeError('response lost after server registration');
   return new Promise((resolve,reject)=>init.signal.addEventListener('abort',()=>reject(new DOMException('aborted','AbortError')),{once:true}));
  }};
 vm.createContext(context);vm.runInContext(source,context);const transport=context.desktopCreateCodecFetch(true),abort=new AbortController();
 const task=transport('http://127.0.0.1/desktop/hls?ep=1',{method:'POST',headers:{'x-api-key':'owned'},signal:abort.signal}).then(()=>assert.fail('creation must reject'),()=>{});
 await Promise.race([started,task.then(()=>assert.fail('creation rejected before tokenized POST'))]);if(fault==='abort')abort.abort();if(fault==='close')transport.close();await task;await tick();
 assert.equal(cancellation,new URL(calls[0].url).searchParams.get('request_token'),'lost or cancelled direct HLS creation is released by its token');transport.close();
}console.log('PASS direct HLS lost response, external abort and close release tokenized creation');})().catch(e=>{console.error(e);process.exitCode=1;});
