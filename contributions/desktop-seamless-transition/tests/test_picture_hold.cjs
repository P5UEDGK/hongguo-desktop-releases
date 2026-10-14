const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const c={WeakMap,Map,Math,Number,Date,window:{},setTimeout:()=>999,clearTimeout(){},
  document:{createElement:()=>({style:{},getContext:()=>({drawImage(){}}),remove(){}})}};
vm.createContext(c);vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../src/frontend-seamless.js'),'utf8'),c);
function media(){return {desktopNativePicture:true,videoWidth:128,videoHeight:128,closest:()=>({append(){}})}}
(async()=>{
  const ended=media();let releases=0;
  assert.equal(c.desktopRetainPicture(ended),null,'last episode/ordinary close has no pending next hold');
  const hold=c.desktopHoldForNext(ended);assert.equal(c.desktopHoldForNext(ended),hold);
  const retain=c.desktopRetainPicture(ended);assert(retain);retain(()=>releases++);
  assert.equal(releases,0,'ending without a successful prewarm keeps its native session');
  assert.equal(await hold.claimRecord('cold-source',0),null,'holder does not pretend to be a ready standby');
  assert.equal(await hold.claim('cold-source',0),null,'legacy HLS cold loading consumes the same retention owner');
  hold.dispose();assert.equal(releases,0,'cold playback owns the retained picture until ready');
  hold.finishRetained();hold.finishRetained();assert.equal(releases,1);
  const cancelled=media(),pending=c.desktopHoldForNext(cancelled);
  c.desktopRetainPicture(cancelled)(()=>releases++);pending.dispose();assert.equal(releases,2,'cancel before cold claim releases');
  c.failedMedia=media();vm.runInContext('desktopStandbys.set(failedMedia,{failed:true})',c);
  const fallback=c.desktopHoldForNext(c.failedMedia);c.desktopRetainPicture(c.failedMedia)(()=>releases++);
  await fallback.claimRecord();fallback.cancelClaim(true);assert.equal(releases,2,'failure fallback retains old frame');
  fallback.cancelClaim();assert.equal(releases,3,'terminal error/close releases retained frame');
  console.log('PASS: no-prewarm/failed-prewarm cold hold, readiness release, last-episode exclusion and cancellation');
})().catch(e=>{console.error(e);process.exitCode=1});
