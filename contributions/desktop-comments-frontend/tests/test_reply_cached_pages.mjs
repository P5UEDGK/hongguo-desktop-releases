import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {createComments}=await import(process.argv[2]?pathToFileURL(process.argv[2]):'../src/comments.mjs');
for(const remount of process.argv[3]?[process.argv[3]==='remount']:[true,false]){
 let slots=[],index=0,tree,round=0,calls=0;
 const React={useState(v){const i=index++;if(!(i in slots))slots[i]=v;return [slots[i],n=>slots[i]=typeof n==='function'?n(slots[i]):n];},useRef(v){const i=index++;return slots[i]??={current:v};},useEffect(fn){const i=index++;if(!slots[i]){slots[i]=true;fn();}}};
 const jsx=(type,props)=>({type,props});const api=createComments({React,jsxRuntime:{jsx,jsxs:jsx},resolveEndpoint(){},installStyles(){},danmaku:{},emojis:{}});
 const endpoint={origin:'http://127.0.0.1:1234',key:'owned',series:'12345678',episode:'1'};
 globalThis.fetch=async url=>{calls++;const params=new URL(url).searchParams,other=params.get('comment_id')!=='parent';const ids=other?[]:params.get('cursor')?['two']:round===0?['one']:round===1?['one','two']:[];return {ok:true,json:async()=>({items:ids.map(id=>({id,author:id,text:id,likes:0,replies:0})),cursor:other||params.get('cursor')||round>0?'':'p2',has_more:!other&&!params.get('cursor')&&round===0})};};
 const store=api.createStore(endpoint),item={id:'parent',author:'owned',text:'parent',likes:0,replies:2};
 function render(){index=0;tree=api.Comment({item,endpoint,store,replies:true});}
 function nodes(n){return Array.isArray(n)?n.flatMap(nodes):n&&typeof n==='object'?[n,...nodes(n.props?.children)]:[];}
 function button(t){render();const node=nodes(tree).find(n=>n.type==='button'&&String(n.props.children).includes(t));assert(node,t);return node;}
 const flush=async()=>{await new Promise(setImmediate);render();};
 const ids=()=>nodes(tree).filter(n=>n.props?.item).map(n=>n.props.item.id);
 button('查看').props.onClick();await flush();button('加载更多回复').props.onClick();await flush();assert.deepEqual(ids(),['one','two']);
 if(remount){button('收起回复').props.onClick();button('查看').props.onClick();await flush();assert.deepEqual(ids(),['one','two'],'reopen does not duplicate cached later replies');slots=[];button('查看').props.onClick();await flush();assert.equal(calls,2);assert.deepEqual(ids(),['one','two'],'remount restores every cached reply page');assert(!nodes(tree).some(n=>n.type==='button'&&n.props.children==='加载更多回复'));}
 else for(round=1;round<=2;round++){
  button('收起回复').props.onClick();for(let n=0;n<33;n++)await store.read('replies',{comment_id:'other'+round+'-'+n,cursor:''});
  button('查看').props.onClick();await flush();assert.deepEqual(ids(),round===1?['one','two']:[],'reply promoted into page one no longer survives its deletion');
 }
 store.dispose();
}
console.log('PASS reply remount hydration and later-page demotion after first-page refresh');
