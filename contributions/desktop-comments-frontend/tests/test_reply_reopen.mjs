import assert from 'node:assert/strict';
import {createComments} from '../src/comments.mjs';
for (const completeWhileHidden of [false,true]) {
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
  button('加载更多回复').props.onClick();button('收起回复').props.onClick();
  if(completeWhileHidden){pending.shift()(page(['two'],false));await flush();}
  button('查看').props.onClick();
  if(!completeWhileHidden)pending.shift()(page(['two'],false));
  await flush();
  const texts=nodes(tree).map(n=>n.props?.item?.text).filter(Boolean);
  assert(texts.includes('two'),'re-expansion reconciles detached reply pagination');assert.equal(calls,2);
  store.dispose();
}
console.log('PASS detached reply pagination reconciles on reopen before and after completion');
