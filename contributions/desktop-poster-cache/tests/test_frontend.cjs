const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('contributions/desktop-poster-cache/src/frontend-posters.js','utf8');
const context=vm.createContext({URL,AbortController,setTimeout,clearTimeout,queueMicrotask,Date,console});
vm.runInContext(source,context);const create=vm.runInContext('desktopCreatePosterLoader',context);
const data='data:image/jpeg;base64,/9j/';const sid='9000000000000001';
test('shared entry batches and merges repeated identity',async()=>{
  const calls=[];const load=create(async ids=>{calls.push([...ids]);return {covers:Object.fromEntries(ids.map(id=>[id,data]))};});
  const one=load(sid),two=load(sid),three=load('9000000000000002');
  assert.equal(one,two);assert.deepEqual(await Promise.all([one,two,three]),[data,data,data]);
  assert.equal(calls.length,1);assert.equal(calls[0].length,2);
});
test('bulk calls bounded and pending identity cleared after error',async()=>{
  let active=0,peak=0,count=0;const load=create(async ids=>{peak=Math.max(peak,++active);count++;
    await new Promise(r=>setTimeout(r,5));active--;return {covers:Object.fromEntries(ids.map(id=>[id,data]))};});
  await Promise.all(Array.from({length:55},(_,i)=>load(String(9000000000000000n+BigInt(i)))));
  assert.equal(count,3);assert.ok(peak<=2);
  let fail=true;const retry=create(async ids=>{if(fail)throw Error('offline');return {covers:{[sid]:data}};});
  await assert.rejects(retry(sid),/offline/);await new Promise(r=>setImmediate(r));fail=false;
  assert.equal(await retry(sid),data);
});
test('invalid identities and unsupported images rejected',async()=>{
  const load=create(async()=>({covers:{[sid]:'data:text/html;base64,foo'}}));
  await assert.rejects(load(9000000000000001),/无效/);await assert.rejects(load(sid),/封面暂不可用/);
});
