const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
(async()=>{
 for(const timerExpiry of [false,true]){
  let now=0,retired=0,token=0;const timers=new Map(),url='http://127.0.0.1/desktop/hls?ep=2';
  const c={WeakMap,Map,Number,Math,AbortController,Date:{now:()=>now},
   setTimeout(fn,delay){timers.set(++token,{fn,delay});return token;},clearTimeout:id=>timers.delete(id),
   w0:()=>({origin:'http://127.0.0.1',url,key:'owned'}),fetch:()=>new Promise(()=>{})};
  vm.createContext(c);vm.runInContext(fs.readFileSync(process.argv[2]||path.join(__dirname,'../src/frontend-seamless.js'),'utf8'),c);
  const current={desktopSessionId:()=> 'a'.repeat(32),playbackRate:2,volume:.4,muted:true};
  const prep=c.desktopPrepareNext(url,current);now=89999;prep.retain(()=>retired++);now=90000;
  if(timerExpiry)[...timers.values()].find(t=>t.delay===90000).fn();
  assert.equal(await prep.claimRecord(url,0),null);prep.dispose();
  assert.equal(retired,0,'expired unclaimed standby retains EOF picture through cold claim/dispose');
  prep.finishRetained();assert.equal(retired,1);timers.clear();
 }
 console.log('PASS: expiry timer and expired claim preserve EOF retention until cold readiness');
})().catch(error=>{console.error(error);process.exitCode=1;});
