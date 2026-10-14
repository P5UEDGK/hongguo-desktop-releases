import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createDesktopRank} from '../src/frontend-rank.mjs';

const rows=[{seriesId:'7690195777649380414',title:'爆笑姐妹',episodeCount:162}];
const reply=(value,status=200)=>({ok:status<400,json:async()=>value});
const api={validationStatus:async()=>({baseUrl:'http://127.0.0.1:12345'})};

test('one GET preserves rank arguments and never queries details',async()=>{
  const original=globalThis.fetch,calls=[];
  globalThis.fetch=async(url,options)=>{calls.push({url:new URL(url),options});return reply(rows);};
  try{
    const rank=createDesktopRank(api);
    assert.deepEqual(await rank('hot'),rows);
    assert.deepEqual(await rank('comic',true,2),rows);
    assert.equal(calls.length,2);
    assert.equal(calls[0].url.pathname,'/desktop/rank');
    assert.equal(calls[0].url.searchParams.get('page'),'1');
    assert.equal(calls[0].url.searchParams.get('refresh'),'false');
    assert.equal(calls[1].url.searchParams.get('board'),'comic');
    assert.equal(calls[1].url.searchParams.get('page'),'2');
    assert.equal(calls[1].url.searchParams.get('refresh'),'true');
    assert.equal(calls[0].options.headers['x-desktop-rank-client'],'1');
    assert.equal(calls[0].options.method??'GET','GET');
    assert.equal(calls[0].options.redirect,'error');
    assert.equal(calls[0].options.credentials,'omit');
    assert.equal(calls[0].options.cache,'no-store');
  }finally{globalThis.fetch=original;}
});

test('HTTP failure propagates without retry or a successful empty list',async()=>{
  const original=globalThis.fetch;let calls=0;
  globalThis.fetch=async()=>{calls++;return reply({detail:'排行榜数据不完整，请重试'},502);};
  try{
    await assert.rejects(createDesktopRank(api)('hot'),/数据不完整/);
    assert.equal(calls,1);
  }finally{globalThis.fetch=original;}
});

test('malformed successful response is rejected without retry',async()=>{
  const original=globalThis.fetch;let calls=0;
  globalThis.fetch=async()=>{calls++;return reply({items:rows});};
  try{
    await assert.rejects(createDesktopRank(api)('hot'),/格式异常/);
    assert.equal(calls,1);
  }finally{globalThis.fetch=original;}
});

test('untrusted service addresses are rejected before network access',async()=>{
  const original=globalThis.fetch;let calls=0;
  globalThis.fetch=async()=>{calls++;throw Error('must not request');};
  try{
    for(const baseUrl of ['https://example.com','http://localhost:12345','http://127.0.0.1',
                         'http://127.0.0.1:12345/path','http://user@127.0.0.1:12345',
                         'http://127.0.0.1:12345?x=1','http://127.0.0.1:12345#x']){
      await assert.rejects(createDesktopRank({validationStatus:async()=>({baseUrl})})('hot'),/本地排行榜服务/);
    }
    assert.equal(calls,0);
  }finally{globalThis.fetch=original;}
});

test('timeout feedback is explicit and no fallback request is issued',async()=>{
  const original=globalThis.fetch;let calls=0;
  globalThis.fetch=async()=>{calls++;throw new DOMException('cancelled','AbortError');};
  try{
    await assert.rejects(createDesktopRank(api)('hot'),/超时/);
    assert.equal(calls,1);
  }finally{globalThis.fetch=original;}
});
