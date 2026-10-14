const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const controllers=[],requests=[];
const media={currentTime:0,playbackRate:1,videoWidth:100,pause(){},play(){return Promise.resolve()},addEventListener(){},removeEventListener(){}};
const c={URL,Headers,Number,Math,Date,queueMicrotask,setTimeout:()=>1,clearTimeout(){},
  fetch:async(url,init={})=>{requests.push(init);return {ok:true,clone(){return this},json:async()=>({id:'a'.repeat(32)})}},
  desktopLegacyHls(m,u,t,callbacks,p,w,transport){transport.usedCopy=()=>controllers.length===1;controllers.push({callbacks,transport});return ()=>{};}};
vm.createContext(c);vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),c);
(async()=>{
  const controller=c.desktopCodecHls(media,'http://127.0.0.1/desktop/hls',0,{onReady(){},onError(){}},null,false,{standbyParent:'b'.repeat(32)});
  await controllers[0].transport('http://127.0.0.1/desktop/hls',{method:'POST'});
  assert.equal(requests[0].headers.get('x-desktop-prewarm-parent'),'b'.repeat(32));
  controller.activate();controllers[0].callbacks.onReady();controllers[0].callbacks.onError();
  assert.equal(controllers.length,2);
  await controllers[1].transport('http://127.0.0.1/desktop/hls',{method:'POST'});
  assert.equal(requests[1].headers.get('x-desktop-prewarm-parent'),null,'post-handoff recovery is ordinary foreground playback');
  controller();console.log('PASS: adopted HLS fallback never reuses the retired parent');
})().catch(e=>{console.error(e);process.exitCode=1});
