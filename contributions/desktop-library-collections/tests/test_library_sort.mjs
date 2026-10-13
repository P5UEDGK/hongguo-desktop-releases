import assert from 'node:assert/strict';
import test from 'node:test';
import {desktopLibrarySortSeasons,desktopLibrarySortGroups} from '../src/library-core.mjs';
import {createLibraryUI} from '../src/frontend-library.mjs';

const row=(season,time=0)=>({seriesId:String(8800000000000002000n+BigInt(season)),title:`作品第${season}季`,updatedAt:time});
const rows=Array.from({length:41},(_,index)=>row(index+1));
const relations=new Map(rows.map((item,index)=>[item.seriesId,{season:index+1,albumId:'8800000000000009000'}]));
test('all 41 seasons sort numerically, input and canonical cover order stay unchanged',()=>{
  const desc=desktopLibrarySortSeasons(rows,relations);
  assert.deepEqual(desc.map(item=>relations.get(item.seriesId).season),Array.from({length:41},(_,i)=>41-i));
  assert.equal(desktopLibrarySortSeasons(desc,relations,'asc')[0],rows[0]);
  assert.equal(rows[0].title,'作品第1季');
});
test('unknown season stays last in both directions, empty and singleton are safe',()=>{
  const unknown=row(99);
  for(const order of ['asc','desc'])assert.equal(desktopLibrarySortSeasons([unknown,...rows],relations,order).at(-1),unknown);
  assert.deepEqual(desktopLibrarySortSeasons([],relations),[]);
  assert.deepEqual(desktopLibrarySortSeasons([unknown],relations),[unknown]);
});
const group=(key,items)=>({key,items});
const a=group('a',[row(1,100),row(2,9999)]),b=group('b',[row(3,200)]);
const names=g=>g.key;
test('recent root ordering uses only that page native records, never another view shared time',()=>{
  assert.deepEqual(desktopLibrarySortGroups([a,b],[row(1,100),row(3,200)],'recent',names),[b,a]);
  assert.deepEqual(desktopLibrarySortGroups([a,b],[row(2,300),row(3,200)],'recent',names),[a,b]);
});
test('recent grouping uses latest member, invalid timestamps have deterministic ties',()=>{
  assert.deepEqual(desktopLibrarySortGroups([a,b],[row(1,100),row(2,300),row(3,200)],'recent',names),[a,b]);
  assert.deepEqual(desktopLibrarySortGroups([b,a],[{...row(1),updatedAt:'invalid'}],'recent',names),[a,b]);
});
test('names use Chinese natural ordering in either direction without mutating groups',()=>{
  const ten=group('作品10',[row(10)]),two=group('作品2',[row(2)]),input=[ten,two];
  assert.deepEqual(desktopLibrarySortGroups(input,[],'title-asc',names),[two,ten]);
  assert.deepEqual(desktopLibrarySortGroups(input,[],'title-desc',names),[ten,two]);
  assert.deepEqual(input,[ten,two]);
});

test('played uses history across all known seasons, not favorite timestamps or episode progress',()=>{
  const input=[a,b],favorites=[row(1,900),row(3,100)],history=[{...row(1,50),lastEpisode:99},{...row(2,300),lastEpisode:1},row(3,200)];
  assert.deepEqual(desktopLibrarySortGroups(input,favorites,'recent',names,history),[a,b]);
  assert.deepEqual(desktopLibrarySortGroups(input,favorites,'played',names,history),[a,b]);
  assert.deepEqual(desktopLibrarySortGroups(input,favorites,'played',names,[row(1,50),row(3,200)]),[b,a]);
  assert.deepEqual(input,[a,b]);assert.equal(history[0].lastEpisode,99);
});

test('played puts unwatched last and breaks equal/missing times by native add time',()=>{
  const c=group('c',[row(4)]),d=group('d',[row(5)]);
  const favorites=[row(1,200),row(3,100),row(4,9999),row(5,300)];
  assert.deepEqual(desktopLibrarySortGroups([c,b,a,d],favorites,'played',names,[row(1,80),row(3,80)]),[a,b,c,d]);
  assert.deepEqual(desktopLibrarySortGroups([c,b,a,d],favorites,'played',names,[row(1,80),{...row(3),updatedAt:'invalid'}]),[a,b,c,d]);
  assert.deepEqual(desktopLibrarySortGroups([a,b,c,d],favorites,'played',names,[]),[c,d,a,b]);
  assert.deepEqual(desktopLibrarySortGroups([],favorites,'played',names,[]),[]);
  assert.deepEqual(desktopLibrarySortGroups([a],favorites,'played',names,[]),[a]);
});
test('factory renders every season, exposes separate persistent controls, sorting starts no searches',()=>{
  const shownRows=rows.map((item,i)=>({...item,title:`持械入宋： 第${i+1}季`}));
  const storage=new Map(),events=new EventTarget();let cursor=0,refCursor=0,searches=0;
  const state=[],refs=[];
  globalThis.localStorage={getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)};
  globalThis.window=events;window.scrollTo=()=>{};window.scrollTo=()=>{};
  globalThis.document={createElement:()=>({}),head:{append:()=>{}}};
  const React={Fragment:Symbol('Fragment'),useEffect:()=>{},
    useState:value=>{const i=cursor++;if(!(i in state))state[i]=typeof value==='function'?value():value;return [state[i],value=>{state[i]=typeof value==='function'?value(state[i]):value;}];},
    useRef:value=>{const i=refCursor++;return refs[i]??=( {current:value});}
  };
  const api={favorites:async()=>shownRows,history:async()=>[],setFavorite:async()=>{},searchNovelfm:async()=>{searches++;throw Error('sorting must not search');}};
  const jsxRuntime={jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})};
  const ui=createLibraryUI({React,jsxRuntime,api,Cover:()=>null});
  for(const [id,relation] of relations)ui.library.relations.set(id,relation);
  const render=()=>{cursor=refCursor=0;return ui.LibraryGrid({items:shownRows,view:'favorites',renderCard:item=>({item})});};
  let tree=render();
  const rootSort=tree.props.children[0].props.children[1];
  assert.equal(rootSort.props.value,'recent');
  const control=rootSort.type(rootSort.props);assert.equal(control.props.children.type,'select');assert.equal(control.props.children.props['aria-label'],'收藏排序');
  assert.deepEqual(control.props.children.props.children.map(option=>option.props.children),['最近播放','最近添加']);
  rootSort.props.onChange('played');
  tree=render();tree.props.children[1].props.children[0].props.children[0].props.onClick();
  tree=render();
  assert.equal(tree.props.children[1].props.children[0].props.children,'持械入宋');
  assert.equal(shownRows[0].title,'持械入宋： 第1季');
  assert.equal(tree.props.children.length,4); // no internal pagination node
  const cards=tree.props.children[3].props.children;
  assert.equal(cards.length,41);assert.equal(cards[0].item,shownRows[40]);
  for(const title of ['问道？ 第1季','问道! 第1季','问道: 第1季']) {
    const old=shownRows[0].title;shownRows[0].title=title;
    assert.equal(render().props.children[1].props.children[0].props.children,title.startsWith('问道:')?'问道':title.split(' ')[0]);
    shownRows[0].title=old;
  }
  const seasonSort=tree.props.children[1].props.children[2];
  assert.equal(seasonSort.props.value,'desc');seasonSort.props.onChange('asc');
  tree=render();assert.equal(tree.props.children[3].props.children[0].item,shownRows[0]);
  assert.deepEqual(JSON.parse(storage.get('guoban:library-sort:v1')),{favorites:'played',seasons:'asc'});
  state.length=0;assert.equal(render().props.children[0].props.children[1].props.value,'played');
  for(const old of ['title-asc','title-desc']){
    storage.set('guoban:library-sort:v1',JSON.stringify({favorites:old,history:'title-desc',seasons:'asc'}));state.length=0;
    assert.equal(render().props.children[0].props.children[1].props.value,'recent');
    assert.equal(JSON.parse(storage.get('guoban:library-sort:v1')).history,'title-desc');
  }
  assert.equal(searches,0);
  delete globalThis.localStorage;
});
