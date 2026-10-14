const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('contributions/desktop-poster-cache/src/frontend-posters.js','utf8');
const context=vm.createContext({URL,AbortController,setTimeout,clearTimeout,queueMicrotask,Date,console,TextDecoder});
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

test('mixed batch releases local image before missing image finishes', {timeout:1500},async()=>{
  const cold='9000000000000002';let release,entered;
  const gate=new Promise(r=>{release=r;}),started=new Promise(r=>{entered=r;});
  const calls=[];
  const load=create(async(ids,{localOnly})=>{
    calls.push({ids:[...ids],localOnly});
    if(localOnly)return {covers:{[sid]:data}};
    entered();await gate;return {covers:Object.fromEntries(ids.map(id=>[id,data]))};
  });
  try {
    const warm=load(sid),remote=load(cold);assert.equal(remote,load(cold));
    await started;assert.equal(await warm,data);
    assert.deepEqual(calls[1].ids,[cold]);
    release();assert.equal(await remote,data);
  } finally {release();}
});

test('occupied download slots never block new disk reads', {timeout:1500},async()=>{
  let release;const gate=new Promise(r=>{release=r;});let remoteStarted=0;
  const calls=[];const load=create(async(ids,{localOnly})=>{
    calls.push({ids:[...ids],localOnly});
    if(localOnly)return {covers:Object.fromEntries(ids.filter(id=>id===sid).map(id=>[id,data]))};
    remoteStarted++;await gate;return {covers:Object.fromEntries(ids.map(id=>[id,data]))};
  });
  const cold=Array.from({length:45},(_,i)=>String(9100000000000000n+BigInt(i)));
  try {
    const work=Promise.all(cold.map(load));
    while(remoteStarted<2)await new Promise(r=>setImmediate(r));
    assert.equal(await load(sid),data);assert.equal(remoteStarted,2);
    assert.ok(calls.filter(c=>!c.localOnly).every(c=>!c.ids.includes(sid)&&c.ids.length<=20));
    release();await work;
  } finally {release();}
});

test('one completed image resolves while its batch still downloads', {timeout:1500},async()=>{
  const slow='9000000000000002';let release,entered;
  const gate=new Promise(r=>release=r),started=new Promise(r=>entered=r);
  const load=create(async(ids,{localOnly},progress)=>{
    if(localOnly)return {covers:{}};
    progress({covers:{[sid]:data}});entered();await gate;
    progress({covers:{[slow]:data}});return {covers:{}};
  });
  try {
    const one=load(sid),two=load(slow);let done=false;two.then(()=>done=true);
    await started;assert.equal(await one,data);assert.equal(done,false);
    release();assert.equal(await two,data);
  } finally {release();}
});

test('stream handles split frames, final line, and rejects malformed data',async()=>{
  const read=vm.runInContext('desktopReadPosterStream',context),encoder=new TextEncoder(),parts=[];
  const bytes=encoder.encode(JSON.stringify({covers:{[sid]:data}})+'\n'+JSON.stringify({covers:{},missing:['中文']}));
  const response=new Response(new ReadableStream({start(c){for(let i=0;i<bytes.length;i+=7)c.enqueue(bytes.slice(i,i+7));c.close();}}));
  await read(response,part=>parts.push(part));assert.equal(parts[0].covers[sid],data);assert.equal(parts[1].missing[0],'中文');
  await assert.rejects(read(new Response('{bad}\n'),()=>{}));
  await assert.rejects(read(new Response('{"covers":[]}\n'),()=>{}),/格式无效/);
});

test('successful streamed image survives later batch failure',async()=>{
  const slow='9000000000000002';
  const load=create(async(ids,{localOnly},progress)=>{
    if(localOnly)return {covers:{}};
    progress({covers:{[sid]:data}});throw Error('stream interrupted');
  });
  const one=load(sid),two=load(slow);await assert.rejects(two,/interrupted/);assert.equal(await one,data);
});
