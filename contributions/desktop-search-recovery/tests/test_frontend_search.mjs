import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createDesktopNovelfmSearch} from '../src/frontend-search.mjs';

const reply = (value, status = 200) => ({ok:status < 400, status, json:async()=>value});
const result = {items:[{seriesId:'7694116863835376664', title:'测试剧', source:'novelfm'}], hasMore:true};

test('search preserves payload and reuses the process token', async () => {
  const previous = globalThis.fetch, calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({url, options});
    return options.method === 'GET' ? reply({requestToken:'fixture-token'}) : reply(result);
  };
  try {
    const search = createDesktopNovelfmSearch({validationStatus:async()=>({baseUrl:'http://127.0.0.1:12345'})});
    assert.deepEqual(await search('中文 & ?', 1, 'manju'), result);
    await search('中文 & ?', 2, 'manju');
    assert.deepEqual(calls.map(row=>row.options.method), ['GET','POST','POST']);
    assert.deepEqual(JSON.parse(calls[1].options.body), {query:'中文 & ?', page:1, mode:'manju'});
    assert.equal(calls[2].options.headers['x-desktop-search-token'], 'fixture-token');
    assert.equal(calls[1].url, 'http://127.0.0.1:12345/desktop/search');
  } finally {globalThis.fetch = previous;}
});

test('401 refreshes the token once after backend restart', async () => {
  const previous = globalThis.fetch, tokens = [], replies = [reply({requestToken:'old'}), reply({detail:'expired'},401), reply({requestToken:'new'}),reply(result)];
  globalThis.fetch = async (_url, options) => {tokens.push(options.headers['x-desktop-search-token']); return replies.shift();};
  try {
    const search = createDesktopNovelfmSearch({validationStatus:async()=>({baseUrl:'http://127.0.0.1:12345'})});
    assert.deepEqual(await search('测试',1,'short'),result);
    assert.deepEqual(tokens,['','old','','new']);
    assert.equal(replies.length,0);
  } finally {globalThis.fetch = previous;}
});

test('persistent 401 stops after the single refresh', async () => {
  const previous = globalThis.fetch; let calls = 0;
  globalThis.fetch = async (_url, options) => {calls++; return options.method === 'GET' ? reply({requestToken:'fixture'}) : reply({detail:'expired'},401);};
  try {
    const search = createDesktopNovelfmSearch({validationStatus:async()=>({baseUrl:'http://127.0.0.1:12345'})});
    await assert.rejects(search('测试',1,'manju'), error=>error.status===401);
    assert.equal(calls,4);
  } finally {globalThis.fetch = previous;}
});

test('upstream failure is an error and never a successful empty list', async () => {
  const previous = globalThis.fetch; let calls = 0;
  globalThis.fetch = async (_url, options) => {calls++;return options.method === 'GET' ? reply({requestToken:'fixture'}) : reply({detail:'搜索服务未返回成功状态，请重试'},502);};
  try {
    const search = createDesktopNovelfmSearch({validationStatus:async()=>({baseUrl:'http://127.0.0.1:12345'})});
    await assert.rejects(search('测试',1,'manju'), error=>error.status===502 && error.message.includes('请重试'));
    assert.equal(calls,2);
  } finally {globalThis.fetch = previous;}
});

test('untrusted backend origins are rejected before any fetch', async () => {
  const previous = globalThis.fetch; let calls = 0;
  globalThis.fetch = async()=>{calls++;throw Error('must not request');};
  try {
    for (const baseUrl of ['https://example.com','http://127.0.0.1:12345/path','http://user@127.0.0.1:12345','http://127.0.0.1:12345?x=1']) {
      const search = createDesktopNovelfmSearch({validationStatus:async()=>({baseUrl})});
      await assert.rejects(search('测试',1,'manju'),/本地搜索服务/);
    }
    assert.equal(calls,0);
  } finally {globalThis.fetch = previous;}
});
