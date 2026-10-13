import assert from 'node:assert/strict';
import test from 'node:test';
import {createLibraryUI} from '../src/frontend-library.mjs';

test('root lists append batches, stop at the end and reset on sorting without data calls',()=>{
  const rows=Array.from({length:37},(_,i)=>({seriesId:String(8800000000000005000n+BigInt(i)),title:`作品${i+1}`,updatedAt:i}));
  const state=[],refs=[],effects=[],observers=[],storage=new Map();let cursor=0,refCursor=0,effectCursor=0,requests=0,scroll=null;
  globalThis.localStorage={getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)};
  globalThis.window=Object.assign(new EventTarget(),{scrollY:600,scrollTo:(x,y)=>{scroll=y;}});
  globalThis.document={createElement:()=>({}),head:{append:()=>{}}};
  globalThis.IntersectionObserver=class {
    constructor(callback,options){this.callback=callback;this.options=options;observers.push(this);}
    observe(node){this.node=node;}
    disconnect(){this.disconnected=true;}
  };
  const React={Fragment:Symbol('Fragment'),cloneElement:(card,props)=>({...card,props}),
    useState:value=>{const i=cursor++;if(!(i in state))state[i]=typeof value==='function'?value():value;return [state[i],next=>{state[i]=typeof next==='function'?next(state[i]):next;}];},
    useRef:value=>{const i=refCursor++;return refs[i]??={current:value};},
    useEffect:(work,deps)=>{const i=effectCursor++,old=effects[i];if(!old||deps.some((value,n)=>!Object.is(value,old.deps[n]))){old?.cleanup?.();effects[i]={work,deps,pending:true};}}
  };
  const api={favorites:async()=>{requests++;return rows;},history:async()=>{requests++;return [];},setFavorite:async()=>{requests++;},searchNovelfm:async()=>{requests++;}};
  const jsxRuntime={jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})};
  const ui=createLibraryUI({React,jsxRuntime,api,Cover:()=>null});
  ui.library.ensure=async()=>{};
  const render=(items=rows,view='favorites')=>{
    cursor=refCursor=effectCursor=0;
    const tree=ui.LibraryGrid({items,view,renderCard:(item,navigation)=>({item,navigation})});
    if(tree.props.children[2]?.props?.ref)tree.props.children[2].props.ref.current={fixture:true};
    for(const effect of effects)if(effect.pending){effect.pending=false;effect.cleanup=effect.work();}
    return tree;
  };
  const count=tree=>tree.props.children[1].props.children.length;
  let tree=render();assert.equal(count(tree),12);assert.equal(observers.length,1);
  assert.equal(observers[0].options.rootMargin,'0px 0px 480px 0px');
  const first=tree.props.children[1].props.children.map(card=>card.item.seriesId);
  observers[0].callback([{isIntersecting:false}]);assert.equal(count(render()),12);
  observers[0].callback([{isIntersecting:true}]);observers[0].callback([{isIntersecting:true}]);
  tree=render();assert.equal(count(tree),24);assert.equal(observers[0].disconnected,true);
  assert.deepEqual(tree.props.children[1].props.children.slice(0,12).map(card=>card.item.seriesId),first);
  tree.props.children[2].props.children.props.onClick();tree=render();assert.equal(count(tree),36);
  tree.props.children[2].props.children.props.onClick();tree=render();assert.equal(count(tree),37);assert.equal(tree.props.children[2],false);
  tree=render(rows.slice(0,1));assert.equal(count(tree),1);assert.equal(tree.props.children[2],false);
  tree=render([]);assert.equal(count(tree),0);assert.equal(tree.props.children[2],false);
  tree=render();tree.props.children[0].props.children[1].props.onChange('played');
  tree=render();assert.equal(count(tree),12);assert.equal(scroll,0);
  assert.equal(tree.props.children[1].props.children[0].item.title,'作品37');
  tree.props.children[2].props.children.props.onClick();tree=render();assert.equal(count(tree),24);
  tree=render(rows,'history');assert.equal(count(tree),12);
  tree=render(rows,'favorites');assert.equal(count(tree),24);
  tree=render(rows.slice(0,13));assert.equal(count(tree),13);assert.equal(tree.props.children[2],false);
  for(const item of rows.slice(0,2))ui.library.relations.set(item.seriesId,{albumId:'8800000000000009000',season:1});
  tree=render();assert.equal(count(tree),24);
  assert.match(tree.props.children[0].props.children[0].props.children,/36 个条目，其中 1 个合集/);
  ui.library.relations.clear();tree=render();assert.equal(count(tree),24);
  tree.props.children[1].props.children[0].navigation.open();tree=render();
  assert.equal(tree.props.className,'desktop-collection-view');
  render(rows,'history');tree=render(rows,'history');
  assert.equal(tree.props.className,'desktop-library-root');
  assert.equal(count(tree),12,'changing view must leave the old collection without restoring its focus/scroll');
  assert.equal(requests,0,'scrolling and sorting must not search, reload records or write membership');
  for(const effect of effects)effect.cleanup?.();
  delete globalThis.IntersectionObserver;delete globalThis.localStorage;
});
