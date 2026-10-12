import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {createComments}=await import(process.argv[2]?pathToFileURL(process.argv[2]):'../src/comments.mjs');
for(const fault of process.argv[3]?[process.argv[3]]:['p2-only','overlap','zero','positive']){
 let slots=[],index=0,tree,round=0,calls=0;const effects=[];
 const React={useState(v){const i=index++;if(!(i in slots))slots[i]=v;return [slots[i],n=>slots[i]=typeof n==='function'?n(slots[i]):n];},useRef(v){const i=index++;return slots[i]??={current:v};},useEffect(fn,deps){const i=index++;if(!slots[i]||deps?.some((v,n)=>v!==slots[i][n])){slots[i]=deps||[];effects.push(fn);}}};
 const jsx=(type,props)=>({type,props}),api=createComments({React,jsxRuntime:{jsx,jsxs:jsx},resolveEndpoint(){},installStyles(){},danmaku:{},emojis:{}});
 const endpoint={origin:'http://127.0.0.1:1234',key:'owned',series:'12345678',episode:'1'};
 globalThis.fetch=async url=>{calls++;const q=new URL(url).searchParams;const other=q.get('comment_id')!=='parent',cursor=q.get('cursor');const ids=other?[]:cursor?(fault==='overlap'?['one','two']:['two']):round?(fault==='positive'?['new']:[]):['one'];return {ok:true,json:async()=>({items:ids.map(id=>({id,author:id,text:id,likes:0,replies:0})),cursor:!other&&!cursor&&!round?'p2':'',has_more:!other&&!cursor&&!round})};};
 const store=api.createStore(endpoint),item={id:'parent',author:'owned',text:'parent',likes:0,replies:2};
 function render(){index=0;tree=api.Comment({item,endpoint,store,replies:true});while(effects.length)effects.shift()();}
 const nodes=n=>Array.isArray(n)?n.flatMap(nodes):n&&typeof n==='object'?[n,...nodes(n.props?.children)]:[];
 function button(text){render();const n=nodes(tree).find(n=>n.type==='button'&&String(n.props.children).includes(text));assert(n,text);return n;}
 const flush=async()=>{await new Promise(setImmediate);render();},ids=()=>nodes(tree).filter(n=>n.props?.item).map(n=>n.props.item.id);
 button('查看').props.onClick();await flush();
 if(fault==='p2-only')for(let n=0;n<33;n++)await store.read('replies',{comment_id:'other0-'+n,cursor:''});
 button('加载更多回复').props.onClick();await flush();assert.deepEqual(ids(),['one','two']);
 if(fault==='p2-only'){slots=[];button('查看').props.onClick();await flush();assert.deepEqual(ids(),['one','two'],'p2-only cache survives restoring page one after remount');}
 if(fault==='overlap'){button('收起回复').props.onClick();round=1;for(let n=0;n<33;n++)await store.read('replies',{comment_id:'other1-'+n,cursor:''});button('查看').props.onClick();await flush();assert.deepEqual(ids(),['two'],'overlapping first-page reply cannot gain later provenance');}
 if(fault==='positive'){round=1;item.replies=3;render();render();assert(!nodes(tree).some(n=>n.props?.className==='desktop-social-replies'));button('查看').props.onClick();await flush();assert.deepEqual(ids(),['new'],'positive reply count changes invalidate a terminal cached thread');}
 if(fault==='zero'){item.replies=0;render();assert(!nodes(tree).some(n=>n.props?.className==='desktop-social-replies'),'zero reply count hides stale panels');item.replies=2;render();assert(!nodes(tree).some(n=>n.props?.className==='desktop-social-replies'),'restored count does not reopen the stale panel');}
 store.dispose();
}
console.log('PASS reply p2-only cache, overlap provenance and count zero edges');
