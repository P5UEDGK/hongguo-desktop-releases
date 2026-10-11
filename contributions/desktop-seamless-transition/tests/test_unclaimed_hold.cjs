const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const url='http://127.0.0.1/desktop/hls?ep=2';let reject,retired=0,timers=[];
const current={desktopSessionId:()=> 'a'.repeat(32),playbackRate:2,volume:.4,muted:true};
const c={WeakMap,Map,Date,Number,Math,AbortController,setTimeout(fn,delay){if(delay===90000)timers.push(fn);return 999;},clearTimeout(){},
  w0:()=>({origin:'http://127.0.0.1',url,key:'owned'}),fetch:()=>new Promise((_,r)=>reject=r)};
vm.createContext(c);vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/frontend-seamless.js'),'utf8'),c);
(async()=>{
 for(const fault of ['source','expiry']){
  retired=0;timers=[];const prep=c.desktopPrepareNext(url,current);assert.equal(c.desktopHoldForNext(current),prep);
  if(fault==='source')reject(Error('source failed before disposer attachment'));else timers[0]();await new Promise(setImmediate);
  const attach=c.desktopRetainPicture(current);assert.equal(typeof attach,'function','hold intent survives failure before retain callback');attach(()=>retired++);
  assert.equal(prep.failed,true);assert.equal(retired,0,'unclaimed EOF retention survives preparation failure');
  assert.equal(await prep.claimRecord(url,0),null);assert.equal(retired,0,'cold claim still owns the picture');
  prep.finishRetained();assert.equal(retired,1);
 }
  console.log('PASS unclaimed preparation failure retains EOF picture until cold readiness');
})().catch(e=>{console.error(e);process.exitCode=1;});
