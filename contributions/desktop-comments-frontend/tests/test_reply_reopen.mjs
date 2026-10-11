import assert from 'node:assert/strict';
import {createComments} from '../src/comments.mjs';
for (const evictBeforePageTwo of [false,true]) for (const completeWhileHidden of [false,true]) {
  let slots=[],index=0,tree,pending=[],calls=0;
  const React={useState(initial){const i=index++;if(!(i in slots))slots[i]=typeof initial==='function'?initial():initial;return [slots[i],v=>{slots[i]=typeof v==='function'?v(slots[i]):v;}];},
    useRef(initial){const i=index++;return slots[i]??=( {current:initial});},useEffect(fn){const i=index++;if(!slots[i]){slots[i]=true;fn();}}};
  const jsx=(type,props)=>({type,props});
  const api=createComments({React,jsxRuntime:{jsx,jsxs:jsx},resolveEndpoint(){},installStyles(){},danmaku:{},emojis:{}});
  const endpoint={origin:'http://127.0.0.1:1234',key:'owned',series:'12345678',episode:'1'};
  globalThis.fetch=()=>{calls++;return new Promise(resolve=>pending.push(result=>resolve({ok:true,json:async()=>result})));};
  const store=api.createStore(endpoint),item={id:'parent',author:'owned',text:'parent',likes:0,replies:2};
  function render(){index=0;tree=api.Comment({item,endpoint,store,replies:true});return tree;}
  function nodes(node){return Array.isArray(node)?node.flatMap(nodes):node&&typeof node==='object'?[node,...nodes(node.props?.children)]:[];}
  function button(text){const node=nodes(render()).find(n=>n.type==='button'&&String(n.props.children).includes(text));assert(node,text);return node;}
  const flush=async()=>{await new Promise(setImmediate);render();};
  const page=(ids,more)=>({items:ids.map(id=>({id,author:id,text:id,likes:0,replies:0})),cursor:more?'p2':'',has_more:more});
  render();button('查看').props.onClick();pending.shift()(page(['one'],true));await flush();
  if(evictBeforePageTwo) for(let n=0;n<33;n++){const loaded=store.read('replies',{comment_id:'other'+n,cursor:''});pending.shift()(page([],false));await loaded;}
  button('加载更多回复').props.onClick();button('收起回复').props.onClick();
  if(completeWhileHidden){pending.shift()(page(['two'],false));await flush();}
  button('查看').props.onClick();
  if(!completeWhileHidden)pending.shift()(page(['two'],false));
  await flush();
  const texts=nodes(tree).map(n=>n.props?.item?.text).filter(Boolean);
  assert(texts.includes('two'),'re-expansion reconciles detached reply pagination');assert.equal(calls,evictBeforePageTwo?35:2);
  store.dispose();
}
console.log('PASS detached reply pagination reconciles on reopen before and after completion');
{
  let slots=[],index=0,tree,calls=[],fail=false;
  const React={useState(v){const i=index++;if(!(i in slots))slots[i]=v;return [slots[i],n=>{slots[i]=typeof n==='function'?n(slots[i]):n;}];},useRef(v){const i=index++;return slots[i]??={current:v};},useEffect(fn){const i=index++;if(!slots[i]){slots[i]=true;fn();}}};
  const jsx=(type,props)=>({type,props});const api=createComments({React,jsxRuntime:{jsx,jsxs:jsx},resolveEndpoint(){},installStyles(){},danmaku:{},emojis:{}});
  const store={async read(resource,params){calls.push(params.cursor);if(fail){fail=false;throw Error('offline');}return {items:[{id:'one',author:'one',text:'one',likes:0,replies:0}],cursor:'p2',has_more:true};}};
  function render(){index=0;tree=api.Comment({item:{id:'parent',author:'owned',text:'parent',likes:0,replies:2},endpoint:{},store,replies:true});}
  function nodes(n){return Array.isArray(n)?n.flatMap(nodes):n&&typeof n==='object'?[n,...nodes(n.props?.children)]:[];}
  function button(t){render();const b=nodes(tree).find(n=>n.type==='button'&&String(n.props.children).includes(t));assert(b,t);return b;}
  const flush=async()=>{await new Promise(setImmediate);render();};
  button('查看').props.onClick();await flush();button('收起回复').props.onClick();fail=true;button('查看').props.onClick();await flush();
  button('重试').props.onClick();await flush();assert.deepEqual(calls,['','',''],'retry uses the failed first-page cursor');
}
console.log('PASS failed reply cursor is retained across stale-page retries');

{
 let slots=[],index=0,tree,calls=0;
 const React={useState(v){const i=index++;if(!(i in slots))slots[i]=v;return [slots[i],n=>slots[i]=typeof n==='function'?n(slots[i]):n];},useRef(v){const i=index++;return slots[i]??={current:v};},useEffect(fn){const i=index++;if(!slots[i]){slots[i]=true;fn();}}};
 const jsx=(type,props)=>({type,props});const api=createComments({React,jsxRuntime:{jsx,jsxs:jsx},resolveEndpoint(){},installStyles(){},danmaku:{},emojis:{}});
 const endpoint={origin:'http://127.0.0.1:1234',key:'owned',series:'12345678',episode:'1'};
 globalThis.fetch=async()=>{const second=++calls===2;return {ok:true,json:async()=>({items:[{id:second?'two':'one',author:'owned',text:second?'two':'one',likes:0,replies:0}],cursor:second?'':'p2',has_more:!second})};};
 function render(){index=0;tree=api.Comment({item:{id:'parent',author:'owned',text:'parent',likes:0,replies:2},endpoint,replies:true});}
 function nodes(n){return Array.isArray(n)?n.flatMap(nodes):n&&typeof n==='object'?[n,...nodes(n.props?.children)]:[];}
 function button(t){render();const b=nodes(tree).find(n=>n.type==='button'&&String(n.props.children).includes(t));assert(b,t);return b;}
 const flush=async()=>{await new Promise(setImmediate);render();};
 button('查看').props.onClick();await flush();button('加载更多回复').props.onClick();await flush();
 button('收起回复').props.onClick();button('查看').props.onClick();await flush();
 assert.equal(calls,2,'standalone reopen preserves the merged reply pages');assert(nodes(tree).some(n=>n.props?.item?.text==='two'));
}
console.log('PASS standalone replies keep pagination on re-expansion');

{
 let slots=[],index=0,tree,calls=0;
 const React={useState(v){const i=index++;if(!(i in slots))slots[i]=v;return [slots[i],n=>slots[i]=typeof n==='function'?n(slots[i]):n];},useRef(v){const i=index++;return slots[i]??={current:v};},useEffect(fn){const i=index++;if(!slots[i]){slots[i]=true;fn();}}};
 const jsx=(type,props)=>({type,props});const api=createComments({React,jsxRuntime:{jsx,jsxs:jsx},resolveEndpoint(){},installStyles(){},danmaku:{},emojis:{}});
 const endpoint={origin:'http://127.0.0.1:1234',key:'owned',series:'12345678',episode:'1'};
 globalThis.fetch=async()=>{const call=++calls,second=call===2;return {ok:true,json:async()=>({items:(call===36?['new','one']:[second?'two':'one']).map(id=>({id,author:call===36?'fresh':id,text:id,likes:0,replies:0})),cursor:second?'':'p2',has_more:!second})};};
 const store=api.createStore(endpoint);
 function render(){index=0;tree=api.Comment({item:{id:'parent',author:'owned',text:'parent',likes:0,replies:2},endpoint,store,replies:true});}
 function nodes(n){return Array.isArray(n)?n.flatMap(nodes):n&&typeof n==='object'?[n,...nodes(n.props?.children)]:[];}
 function button(t){render();const b=nodes(tree).find(n=>n.type==='button'&&String(n.props.children).includes(t));assert(b,t);return b;}
 const flush=async()=>{await new Promise(setImmediate);render();};
 button('查看').props.onClick();await flush();button('加载更多回复').props.onClick();await flush();
 button('收起回复').props.onClick();
 for(let n=0;n<33;n++)await store.read('replies',{comment_id:'other'+n,cursor:''});
 button('查看').props.onClick();await flush();
 assert.equal(calls,36,'store eviction refetches only the first page');assert(nodes(tree).some(n=>n.props?.item?.text==='two'),'evicted first page keeps later replies');
 assert(!nodes(tree).some(n=>n.type==='button'&&n.props.children==='加载更多回复'),'reconciliation retains the final cursor');
 assert.deepEqual(nodes(tree).filter(n=>n.props?.item).map(n=>n.props.item.id),['new','one','two'],'refreshed first page appears before retained later pages');
 assert.equal(nodes(tree).find(n=>n.props?.item?.id==='one').props.item.author,'fresh');store.dispose();
}
console.log('PASS store eviction preserves later replies and final cursor');

for (const freshIds of [[],['new']]) {
 let slots=[],index=0,tree,calls=0;
 const React={useState(v){const i=index++;if(!(i in slots))slots[i]=v;return [slots[i],n=>slots[i]=typeof n==='function'?n(slots[i]):n];},useRef(v){const i=index++;return slots[i]??={current:v};},useEffect(fn){const i=index++;if(!slots[i]){slots[i]=true;fn();}}};
 const jsx=(type,props)=>({type,props});const api=createComments({React,jsxRuntime:{jsx,jsxs:jsx},resolveEndpoint(){},installStyles(){},danmaku:{},emojis:{}});
 const endpoint={origin:'http://127.0.0.1:1234',key:'owned',series:'12345678',episode:'1'};
 globalThis.fetch=async()=>{const call=++calls,second=call===2;return {ok:true,json:async()=>({items:(call===35?freshIds:['one']).map(id=>({id,author:call===36?'fresh':id,text:id,likes:0,replies:0})),cursor:call===35?'':'p2',has_more:call!==35})};};
 const store=api.createStore(endpoint);
 function render(){index=0;tree=api.Comment({item:{id:'parent',author:'owned',text:'parent',likes:0,replies:2},endpoint,store,replies:true});}
 function nodes(n){return Array.isArray(n)?n.flatMap(nodes):n&&typeof n==='object'?[n,...nodes(n.props?.children)]:[];}
 function button(t){render();const b=nodes(tree).find(n=>n.type==='button'&&String(n.props.children).includes(t));assert(b,t);return b;}
 const flush=async()=>{await new Promise(setImmediate);render();};
 button('查看').props.onClick();await flush();
 button('收起回复').props.onClick();
 for(let n=0;n<33;n++)await store.read('replies',{comment_id:'other'+n,cursor:''});
 button('查看').props.onClick();await flush();
 assert.equal(calls,35);assert.deepEqual(nodes(tree).filter(n=>n.props?.item).map(n=>n.props.item.id),freshIds,'first-page refetch drops removed replies without later-page provenance');
 assert(!nodes(tree).some(n=>n.type==='button'&&n.props.children==='加载更多回复'),'obsolete first-page cursor is replaced');store.dispose();
}
console.log('PASS first-page refresh removes deleted replies and obsolete cursor');
