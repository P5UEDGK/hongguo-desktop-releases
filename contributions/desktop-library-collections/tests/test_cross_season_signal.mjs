import test from 'node:test';
import assert from 'node:assert/strict';
import {createSeasonPlayback,createContinuationRequest} from '../src/season-playback.mjs';
const turn=()=>new Promise(r=>setImmediate(r));
const settle=async()=>{for(let i=0;i<8;i++)await turn();};
function fixture(episode=1){
 const calls=[];let searches=0,healthy=true,parent='a'.repeat(32);
 const media=Object.assign(new EventTarget(),{paused:false,seeking:false,ended:false,desktopSessionId:()=>parent});
 const session={seriesId:'8800000000000002001',episode,total:3,source:'authorizedLocalApi'};
 const config={series:{seriesId:session.seriesId},session,media,enabled:true,healthy:()=>healthy};
 const controller=createSeasonPlayback({find:async()=>{searches++;return {automatic:true,items:[{seriesId:'8800000000000002002'}]};},resolve:()=>{throw Error('not last');},prepare:()=>{throw Error('not last');},shouldPrewarm:()=>false,prefetch:(...args)=>calls.push(args)});
 return {controller,config,media,calls,get searches(){return searches;},health:value=>{healthy=value;},parent:value=>{parent=value;}};
}
test('enables continuous queue before penultimate without searching, coalesces events, closes captured parent',async()=>{
 const f=fixture(),dispose=f.controller.attach(f.config);await settle();
 assert.equal(f.calls.length,1);assert.equal(f.calls[0][2],true);assert.equal(f.searches,0);
 for(let i=0;i<10;i++)f.media.dispatchEvent(new Event('timeupdate'));await settle();assert.equal(f.calls.length,1);
 f.parent('b'.repeat(32));dispose();await settle();assert.equal(f.calls[1][1],'a'.repeat(32));assert.equal(f.calls[1][2],false);assert.ok(f.calls[1][3]>f.calls[0][3]);
});
test('buffering and seeking suspend cross-season queue, recovery resumes with increasing revisions',async()=>{
 const f=fixture();f.controller.attach(f.config);await settle();f.health(false);f.media.dispatchEvent(new Event('waiting'));await settle();assert.equal(f.calls.at(-1)[2],false);
 f.health(true);f.media.dispatchEvent(new Event('playing'));await settle();assert.equal(f.calls.at(-1)[2],true);
 f.media.seeking=true;f.media.dispatchEvent(new Event('seeking'));await settle();assert.equal(f.calls.at(-1)[2],false);
 f.media.seeking=false;f.media.dispatchEvent(new Event('seeked'));await settle();assert.equal(f.calls.at(-1)[2],true);
 assert.ok(f.calls.every((v,i)=>!i||v[3]>f.calls[i-1][3]));f.controller.cancel();await settle();assert.equal(f.calls.at(-1)[2],false);
});
test('newly confirmed next season rechecks the same cache path once without extra finder calls',async()=>{
 const f=fixture(2);f.controller.attach(f.config);await settle();assert.equal(f.searches,1);assert.equal(f.calls.length,2);assert.ok(f.calls[1][3]>f.calls[0][3]);
 f.media.dispatchEvent(new Event('timeupdate'));await settle();assert.equal(f.calls.length,2);assert.equal(f.searches,1);
});

test('request adapter uses managed credentials, body revision, no cookies and bounded error propagation',async()=>{
 const calls=[];const send=createContinuationRequest(url=>({origin:'http://127.0.0.1:12345',key:'fixture'}),async(...args)=>{calls.push(args);return {ok:true,json:async()=>({accepted:true})};});
 await send({streamUrl:'managed'},'a'.repeat(32),true,7);
 assert.equal(calls[0][0],'http://127.0.0.1:12345/desktop/hls/'+'a'.repeat(32)+'/continuation');
 assert.deepEqual(JSON.parse(calls[0][1].body),{enabled:true,revision:7});assert.equal(calls[0][1].headers['x-api-key'],'fixture');assert.equal(calls[0][1].credentials,'omit');assert.equal(calls[0][1].keepalive,false);
 await send({streamUrl:'managed'},'a'.repeat(32),false,8);assert.equal(calls[1][1].keepalive,true);
 const fail=createContinuationRequest(()=>({origin:'http://127.0.0.1:12345',key:'fixture'}),async()=>({ok:false}));await assert.rejects(fail({streamUrl:'managed'},'a'.repeat(32),true,9));
});

test('a standby not yet activated retries once after activation, without unbounded requests',async()=>{
 const media=Object.assign(new EventTarget(),{paused:false,seeking:false,ended:false,desktopSessionId:()=> 'c'.repeat(32)}),calls=[];
 const controller=createSeasonPlayback({find:()=>{throw Error('too early');},resolve:()=>{},prepare:()=>{},shouldPrewarm:()=>false,prefetch:(...args)=>{calls.push(args);return {accepted:false};}});
 const config={series:{seriesId:'8800000000000002001'},session:{seriesId:'8800000000000002001',episode:1,total:3},media,enabled:true,healthy:()=>true};
 controller.attach(config);await settle();assert.equal(calls.length,1);
 await new Promise(r=>setTimeout(r,300));media.dispatchEvent(new Event('playing'));await settle();assert.equal(calls.length,2);
 await new Promise(r=>setTimeout(r,300));media.dispatchEvent(new Event('timeupdate'));await settle();assert.equal(calls.length,2);controller.cancel();await settle();assert.equal(calls.at(-1)[2],false);
});
