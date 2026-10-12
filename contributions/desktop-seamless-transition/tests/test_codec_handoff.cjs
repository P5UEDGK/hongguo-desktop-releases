const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const controllers=[],requests=[];let plays=0;
const media={currentTime:0,playbackRate:1,videoWidth:100,pause(){},play(){plays++;return Promise.resolve()},addEventListener(){},removeEventListener(){}};
const c={crypto:require('node:crypto').webcrypto,AbortController,URL,Headers,Number,Math,Date,queueMicrotask,setTimeout:()=>1,clearTimeout(){},
  fetch:async(url,init={})=>{requests.push(init);return {ok:true,clone(){return this},json:async()=>({id:'a'.repeat(32)})}},
  desktopLegacyHls(m,u,t,callbacks,p,w,transport){transport.usedCopy=()=>controllers.length===1;controllers.push({callbacks,transport});return ()=>{};}};
c.ek=(m,u,t,callbacks,p,transport)=>c.desktopLegacyHls(m,u,t,callbacks,p,true,transport);
vm.createContext(c);vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),c);
(async()=>{
  const controller=c.desktopCodecHls(media,'http://127.0.0.1/desktop/hls',0,{onReady(){},onError(){}},null,false,{standbyParent:'b'.repeat(32)});
  await controllers[0].transport('http://127.0.0.1/desktop/hls',{method:'POST'});
  assert.equal(requests[0].headers.get('x-desktop-prewarm-parent'),'b'.repeat(32));
  await media.play();assert.equal(plays,0,'standby suppresses legacy auto-play until explicit activation');
  controller.activate();controllers[0].callbacks.onReady();controllers[0].callbacks.onError();
  await media.play();assert.equal(plays,1,'adopted controller restores normal playback');
  assert.equal(controllers.length,2);
  await controllers[1].transport('http://127.0.0.1/desktop/hls',{method:'POST'});
  assert.equal(requests[1].headers.get('x-desktop-prewarm-parent'),null,'post-handoff recovery is ordinary foreground playback');
  controller();
  const resumed=c.desktopCodecHls(media,'http://127.0.0.1/desktop/hls',39.5,{onReady(){},onError(){}},{resumePosition:39.5,dispose(){}},true);
  assert.equal(controllers.at(-1).callbacks.preserveResumePosition,true,'explicit standby resume fallback must bypass legacy last-three-seconds restart');
  resumed();
  for(const drift of [.01,.04,.06]){const dispose=c.desktopCodecHls(media,'http://127.0.0.1/desktop/hls',39.5-drift,{onReady(){},onError(){}},{resumePosition:39.5,dispose(){}},true);assert.equal(controllers.at(-1).callbacks.preserveResumePosition,drift<=.05,'resume marker matches the accepted decoded-frame tolerance');dispose();}
  console.log('PASS: adopted HLS fallback never reuses the retired parent; explicit resume bypasses last-three-seconds restart');
})().catch(e=>{console.error(e);process.exitCode=1});
