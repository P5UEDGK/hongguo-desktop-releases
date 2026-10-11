// Cross-package behavior tests; fixtures contain no provider or user data.
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {resolve,dirname,sep} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
const here=dirname(fileURLToPath(import.meta.url));
const args=process.argv.slice(2), option=(name,fallback)=>args.includes(name)?args[args.indexOf(name)+1]:fallback;
const root=resolve(option('--contributions-root',resolve(here,'../..')));
const require=createRequire(resolve(option('--node-modules',resolve(here,'../node_modules')),'_probe.cjs'));
const {chromium}=require('playwright');
const react=await readFile(resolve(dirname(require.resolve('react')),'umd/react.production.min.js'));
const reactdom=await readFile(resolve(dirname(require.resolve('react-dom')),'umd/react-dom.production.min.js'));
const html=`<!doctype html><meta charset="utf-8"><style>
*{box-sizing:border-box}body{margin:0;background:#151619;color:#eee;font:14px sans-serif}
.desktop-player{height:600px;display:flex;flex-direction:column}.desktop-player header{position:relative;height:60px;flex-shrink:0;padding:8px}
.desktop-player-layout{display:grid;flex:1;min-height:0;grid-template-columns:minmax(0,1fr) 360px}
.player-stage{position:relative;min-width:0;min-height:0;background:black}video{width:100%;height:100%;display:block}
.player-chrome{position:absolute;bottom:0;left:0;right:0;padding:30px 16px 10px}.player-toolbar{display:flex;gap:8px;align-items:center;height:40px}.player-clock{font-size:13px}.player-toolbar-spacer{flex:1}.player-toolbar select{width:62px}.player-toolbar>input{width:64px}
.desktop-player button{padding:8px 12px;border:1px solid transparent;border-radius:4px;background:#303236;color:inherit}
.desktop-player .player-toolbar button{border:0;border-radius:4px;background:transparent;display:grid;place-items:center;padding:6px}
.desktop-player button:hover:not(:disabled){color:#fb7299;background:#3a3c40}
aside{display:flex;flex-direction:column;min-height:0;overflow:auto}.episode-fixture{padding:14px;display:flex;flex-direction:column;flex-shrink:0}
.window-controls{position:fixed;right:8px;top:8px;display:flex;gap:6px;height:32px;z-index:10}
.window-controls button,.player-mini-toggle{width:36px;height:32px}.window-pin{position:absolute;right:138px}
.player-mini-toggle{position:absolute;top:8px;right:160px}.return-button{width:120px;height:36px}
</style><div id="root"></div><script src="/react.js"></script><script src="/reactdom.js"></script>
<script type="module">
import {createSocialUI} from '/desktop-social-layout/src/bootstrap.mjs';
const O=window.React,b={jsx:(type,props,key)=>O.createElement(type,{...props,key}),jsxs:(type,props,key)=>O.createElement(type,{...props,key})};
const social=createSocialUI({React:O,jsxRuntime:b,resolveEndpoint:url=>({url,origin:location.origin,key:'fixture-only'})});
const {Selection,danmaku}=social;
window.calls=[]; window.hold=false;window.failComments=false;window.aborted=0;window.pendingReads=[];window.releaseReads=()=>{const rows=pendingReads.splice(0);rows.forEach(f=>f());};
const realFetch=window.fetch;
window.fetch=(url,options)=>{
 const path=new URL(url).pathname, params=new URL(url).searchParams;
 if(!path.startsWith('/desktop/social/'))return realFetch(url,options);
 window.calls.push({path,params:Object.fromEntries(params),headers:options.headers});
 if(window.failComments && path.endsWith('/comments'))return Promise.resolve({ok:false});
 let value={items:{}};
 if(path.endsWith('/emojis'))value={items:{'[测试]':'data:image/png;base64,iVBORw0KGgo='}};
 if(path.endsWith('/metrics'))value={likes:4,comments:3,favorites:18};
 if(path.endsWith('/danmaku'))value={items:[{id:'3000000000000000001',text:'test[测试]👍',offset_ms:1000}],next_offset_ms:30000,has_more:false,cursor:''};
 if(path.endsWith('/comments')||path.endsWith('/replies'))value={items:[{id:params.get('cursor')?'3000000000000000002':'3000000000000000001',author:'fixture',text:params.get('kind')==='series'?'series fixture':'constructor <img onerror=alert(1)>[测试]👍[未知]',likes:2,replies:path.endsWith('/replies')?0:1,created_at:0,image_count:0}],cursor:params.get('cursor')?'':'opaque:+/==',has_more:!params.get('cursor'),total:2};
 if(window.hold && /comments|metrics|replies/.test(path))return new Promise((resolve,reject)=>{let done=false;pendingReads.push(()=>{done=true;resolve({ok:true,json:async()=>value});});options.signal.addEventListener('abort',()=>{if(!done){window.aborted++;reject(new DOMException('Aborted','AbortError'));}},{once:true});});
 return Promise.resolve({ok:true,json:async()=>value});
};
function App(){
 const media=O.useRef(null),[ep,setEp]=O.useState(1);window.changeEpisode=()=>setEp(n=>n+1);
 O.useEffect(()=>{
  const video=media.current,stage=video.closest('.player-stage');
  const toggle=()=>video.paused?video.play():video.pause();
  const click=event=>{if(event.target===video)toggle();};
  // Stand-in for the existing host control owner; social must not bind a second toggle.
  let paused=false;window.toggleCount=0;
  Object.defineProperty(video,'paused',{configurable:true,get:()=>paused});
  video.play=()=>{paused=false;window.toggleCount++;return Promise.resolve();};
  video.pause=()=>{paused=true;window.toggleCount++;};
  stage.addEventListener('click',click);window.fixtureToggle=toggle;
  return()=>stage.removeEventListener('click',click);
 },[]);
 const session={streamUrl:location.origin+'/stream?series_id=1000000000000000001&ep='+ep};
 return b.jsxs('div',{className:'app-shell',children:[
 b.jsxs('div',{className:'window-controls dark compact',children:['置顶','最小化','最大化','关闭'].map((label,i)=>b.jsx('button',{className:i===0?'window-pin':'','aria-label':label,children:label},label))}),
 b.jsxs('div',{className:'desktop-player',children:[
 b.jsxs('header',{children:[b.jsx('button',{className:'return-button',children:'返回片单'}),b.jsx(Selection,{media,sessionKey:session.streamUrl}),b.jsx('button',{className:'player-mini-toggle','aria-label':'迷你窗口',children:'小窗'})]}),
 b.jsxs('main',{className:'desktop-player-layout',children:[b.jsxs('div',{className:'player-stage',children:[b.jsx('video',{ref:media}),b.jsx('div',{className:'player-chrome',children:b.jsxs('div',{className:'player-toolbar',children:[b.jsx('button',{'aria-label':'播放或暂停',onClick:()=>window.fixtureToggle(),children:b.jsx('svg',{width:22,height:22,viewBox:'0 0 24 24',children:b.jsx('path',{d:'M5 3L21 12L5 21Z',fill:'currentColor'})})}),...['上一集','下一集'].map(label=>b.jsx('button',{'aria-label':label,children:b.jsx('svg',{width:22,height:22})},label)),b.jsx('span',{className:'player-clock',children:'00:27 / 01:36'}),b.jsx('span',{className:'player-toolbar-spacer'}),b.jsx(social.Controls,{media,sessionKey:session.streamUrl}),b.jsx('select',{'aria-label':'播放速度',children:b.jsx('option',{children:'2x'})}),b.jsx('button',{'aria-label':'静音',children:b.jsx('svg',{width:22,height:22})}),b.jsx('input',{type:'range','aria-label':'音量'}),...['剧场模式','全屏'].map(label=>b.jsx('button',{'aria-label':label,children:b.jsx('svg',{width:22,height:22})},label))]})})]}),
 b.jsxs('aside',{children:[b.jsx(social.Drawer,{session,media}),b.jsx('div',{className:'episode-fixture',children:Array.from({length:40},(_,i)=>b.jsx('button',{children:'第 '+(i+1)+' 集'},i))})]})]})]})]});
}
ReactDOM.createRoot(document.getElementById('root')).render(b.jsx(App,{}));
window.socialApi=social;window.danmakuApi=danmaku;
</script>`;
const server=createServer(async(req,res)=>{
 try{
  const url=new URL(req.url,'http://localhost');
  if(url.pathname==='/'){res.setHeader('content-type','text/html; charset=utf-8');res.end(html);return;}
  if(url.pathname==='/react.js'||url.pathname==='/reactdom.js'){res.setHeader('content-type','application/javascript');res.end(url.pathname==='/react.js'?react:reactdom);return;}
  const file=resolve(root,'.'+decodeURIComponent(url.pathname));
  if(!file.startsWith(root+sep)||!file.endsWith('.mjs'))throw Error('Forbidden');
  res.setHeader('content-type','application/javascript');res.end(await readFile(file));
 }catch{res.writeHead(404);res.end();}
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
let browser;
const errors=[];let count=0;
function check(value,message){assert.ok(value,message);console.log('PASS '+message);count++;}
try{
 browser=await chromium.launch({channel:option('--channel','chrome'),headless:true});
 const page=await browser.newPage({viewport:{width:1280,height:720}});
 page.on('pageerror',e=>errors.push(String(e)));
 await page.addInitScript(()=>localStorage.setItem('hongguo:social','on'));
 await page.goto('http://127.0.0.1:'+server.address().port);
 await page.getByRole('tab',{name:'选集',exact:true}).waitFor({timeout:5000}).catch(async e=>{console.error('PAGE ERRORS',errors,'BODY',await page.locator('body').innerText());throw e;});
 const socialCalls=()=>page.evaluate(()=>calls.filter(c=>/comments|metrics|replies/.test(c.path)));
 check((await socialCalls()).length===0,'remembered open drawer starts on episodes without comments/metrics/replies');
 check(await page.getByRole('button',{name:'关闭选集',exact:true}).getAttribute('aria-expanded')==='true','remembered-open selection exposes its closing action and expanded state');
 check(await page.getByRole('button',{name:'评论与互动',exact:true}).getAttribute('aria-pressed')==='false'&&await page.getByRole('button',{name:'评论与互动',exact:true}).getAttribute('aria-expanded')===null,'disabled comments use pressed state while the remembered drawer stays expanded');
 check(await page.locator('aside').evaluate(n=>n.firstElementChild.classList.contains('desktop-social')),'drawer navigation is first in DOM order');
 await page.getByRole('tab',{name:'选集',exact:true}).focus();await page.keyboard.press('Tab');
 check(await page.getByRole('button',{name:'关闭右侧抽屉',exact:true}).evaluate(n=>n===document.activeElement),'keyboard reaches visible close control before episode list');
 check(await page.locator('aside').evaluate(n=>{n.scrollTop=n.scrollHeight;const b=n.getBoundingClientRect(),last=n.querySelector('.episode-fixture').lastElementChild.getBoundingClientRect();return n.scrollTop>0&&last.bottom<=b.bottom+1;}),'overflowing episode rows remain reachable by scrolling');
 await page.locator('aside').evaluate(n=>n.scrollTop=0);
 check(await page.getByRole('tab').allTextContents().then(x=>x.join('|')==='选集'),'comments disabled initially exposes selection alone');
 check(await page.locator('.desktop-social-header,.desktop-social-toolbar').count()===0,'selection hides title and all statistics');
 check(await page.getByRole('button',{name:'关闭右侧抽屉',exact:true}).isVisible(),'selection retains a close button');
 await page.locator('video').click({position:{x:80,y:80}});
 check(await page.locator('video').evaluate(v=>v.paused)&&await page.evaluate(()=>toggleCount===1),'single picture click pauses exactly once');
 await page.locator('video').click({position:{x:80,y:80}});
 check(await page.locator('video').evaluate(v=>!v.paused)&&await page.evaluate(()=>toggleCount===2),'second picture click resumes exactly once');
 await page.getByRole('button',{name:'播放或暂停',exact:true}).click();
 check(await page.evaluate(()=>toggleCount===3),'toolbar click does not toggle twice through the stage');
 const playBox=await page.getByRole('button',{name:'播放或暂停',exact:true}).boundingBox(), iconBox=await page.getByRole('button',{name:'播放或暂停',exact:true}).locator('svg').boundingBox();
 check(Math.abs(iconBox.x+iconBox.width/2-playBox.x-playBox.width/2)<.5&&Math.abs(iconBox.y+iconBox.height/2-playBox.y-playBox.height/2)<.5,'play icon and hover background share a center under host button styles');
 async function singleRow(width){
  await page.setViewportSize({width,height:720});
  await page.waitForTimeout(80);
  const result=await page.locator('.player-toolbar').evaluate(toolbar=>{
   const stage=toolbar.closest('.player-stage').getBoundingClientRect();
   const controls=[...toolbar.children].map(n=>n.getBoundingClientRect());
   const centers=controls.filter(r=>r.width>0&&r.height>0).map(r=>r.top+r.height/2);
   return {contained:controls.every(r=>r.left>=stage.left-.5&&r.right<=stage.right+.5),single:Math.max(...centers)-Math.min(...centers)<1};
  });
  check(result.contained&&result.single,'all full host controls stay on one row at '+width+'px with drawer open');
 }
 for(const width of [1280,850,640])await singleRow(width);
 await page.evaluate(()=>document.querySelector('.desktop-player').classList.add('theater'));
 await singleRow(640);
 await page.evaluate(()=>document.querySelector('.desktop-player').classList.remove('theater'));
 await page.setViewportSize({width:1280,height:720});
 const initial=await page.locator('.desktop-player').boundingBox();
 await page.getByRole('button',{name:'关闭选集',exact:true}).click();
 const wide=await page.locator('video').boundingBox();
 check(await page.getByRole('button',{name:'打开选集',exact:true}).getAttribute('aria-expanded')==='false','closed selection exposes opener and collapsed state');
 await page.getByRole('button',{name:'打开选集',exact:true}).click();
 const narrow=await page.locator('video').boundingBox();
 check(narrow.width<wide.width,'drawer opening narrows video');
 check(JSON.stringify(await page.locator('.desktop-player').boundingBox())===JSON.stringify(initial),'player outer frame remains fixed');
 await page.evaluate(()=>document.querySelector('.desktop-player').classList.add('mini'));
 check(await page.locator('aside').isHidden(),'mini mode hides an already enabled drawer');
 check(Math.abs((await page.locator('video').boundingBox()).width-wide.width)<1,'mini mode restores a single full-width video column');
 await page.waitForTimeout(100);
 const pinMini=await page.locator('.window-pin').boundingBox(),toggleMini=await page.locator('.player-mini-toggle').boundingBox();
 check(Math.min(pinMini.x+pinMini.width,toggleMini.x+toggleMini.width)<=Math.max(pinMini.x,toggleMini.x),'visible mini toggle avoids measured pin');
 await page.evaluate(()=>document.querySelector('.desktop-player').classList.remove('mini'));
 await page.getByRole('button',{name:'评论与互动',exact:true}).click();
 check(await page.getByRole('button',{name:'评论与互动',exact:true}).getAttribute('aria-pressed')==='true','enabled comments expose pressed state');
 await page.getByText('整剧收藏 18',{exact:true}).waitFor();
 check((await socialCalls()).some(c=>c.path.endsWith('/comments')),'comments load on explicit request');
 check(await page.locator('.desktop-social-header,h3').count()===0,'comment tab has no redundant title row');
 const tabBox=await page.getByRole('tab',{name:'本集评论',exact:true}).boundingBox(), closeBox=await page.getByRole('button',{name:'关闭评论页面',exact:true}).boundingBox();
 check(Math.abs(tabBox.y+tabBox.height/2-closeBox.y-closeBox.height/2)<1,'close button aligns with tabs and content moves up');
 const cachedRequestCount=(await socialCalls()).length;
 await page.getByRole('button',{name:'评论与互动',exact:true}).click();
 check(await page.locator('aside').isVisible(),'comment toggle retains the right drawer');
 check(Math.abs((await page.locator('video').boundingBox()).width-narrow.width)<1,'closing comments preserves video width');
 check(await page.getByRole('tab',{name:'选集',selected:true}).isVisible(),'comment toggle returns to selection');
 check(await page.getByRole('tab').allTextContents().then(x=>x.join('|')==='选集'),'bottom toggle removes both comment tabs');
 check(await page.getByRole('button',{name:'评论与互动',exact:true}).getAttribute('aria-pressed')==='false','disabled comments expose unpressed state while selection remains open');
 await page.getByRole('button',{name:'评论与互动',exact:true}).click();
 await page.getByText('整剧收藏 18',{exact:true}).waitFor();
 await page.getByRole('button',{name:'关闭评论页面',exact:true}).click();
 check(await page.locator('aside').isVisible()&&await page.getByRole('tab',{name:'选集',selected:true}).isVisible(),'episode comment close returns to selection and retains drawer');
 check((await socialCalls()).length===cachedRequestCount,'completed comments and metrics are reused across close and reopen');
 check(Math.abs((await page.locator('video').boundingBox()).width-narrow.width)<1,'episode comment close preserves video width');
 check(await page.getByRole('tab',{name:'选集',exact:true}).evaluate(n=>n===document.activeElement),'comment close focuses the selection tab');
 await page.getByRole('button',{name:'关闭右侧抽屉',exact:true}).click();
 check(await page.locator('aside').isHidden(),'selection close button closes the entire drawer after comments');
 check(Math.abs((await page.locator('video').boundingBox()).width-wide.width)<1,'selection close restores full video width');
 check(await page.getByRole('button',{name:'打开选集',exact:true}).evaluate(n=>n===document.activeElement),'selection close restores focus to its opener');
 await page.getByRole('button',{name:'评论与互动',exact:true}).click();
 await page.getByText('整剧收藏 18',{exact:true}).waitFor();
 await page.getByRole('button',{name:'刷新互动计数',exact:true}).click();
 await page.waitForFunction(()=>calls.some(c=>c.path.endsWith('/metrics')&&c.params.refresh==='true'));
 await page.getByRole('tab',{name:'选集',exact:true}).click();
 await page.getByRole('tab',{name:'本集评论',exact:true}).click();
 await page.getByText('整剧收藏 18',{exact:true}).waitFor();
 check(await page.evaluate(()=>calls.filter(c=>c.path.endsWith('/metrics')).length===2),'reopening reuses the manually refreshed metrics without another request');
 check(await page.locator('.desktop-social-item > p img').count()===1,'comments render known emojis');
 check((await page.locator('.desktop-social-item > p').textContent()).includes('constructor <img onerror=alert(1)>'),'untrusted content remains text');
 check(await page.locator('.desktop-social-item img[onerror]').count()===0,'no HTML injection');
 await page.getByRole('button',{name:'加载更多评论',exact:true}).click();
 await page.waitForFunction(()=>document.querySelectorAll('.desktop-social-list > article').length===2);
 check((await socialCalls()).some(c=>c.params.cursor==='opaque:+/=='),'opaque cursor passes unchanged');
 await page.getByRole('button',{name:'查看 1 条回复',exact:true}).first().click();
 await page.locator('.desktop-social-replies article').waitFor();
 check((await socialCalls()).some(c=>c.path.endsWith('/replies')),'replies fetched only when expanded');
 await page.getByRole('tab',{name:'整剧剧评',exact:true}).click();
 await page.getByText('series fixture',{exact:true}).waitFor();
 check(await page.getByRole('button',{name:'查看 1 条回复',exact:true}).count()===0,'series review does not expose episode reply controls');
 await page.getByRole('button',{name:'评论与互动',exact:true}).click();
 check(await page.getByRole('tab').allTextContents().then(x=>x.join('|')==='选集')&&await page.locator('aside').isVisible(),'bottom toggle from series review removes both comment tabs and keeps selection');
 await page.getByRole('button',{name:'评论与互动',exact:true}).click();
 await page.getByRole('tab',{name:'整剧剧评',exact:true}).click();
 await page.getByText('series fixture',{exact:true}).waitFor();
 await page.getByRole('button',{name:'关闭评论页面',exact:true}).click();
 check(await page.locator('aside').isVisible()&&await page.getByRole('tab',{name:'选集',selected:true}).isVisible(),'series review close returns to selection and retains drawer');
 check(Math.abs((await page.locator('video').boundingBox()).width-narrow.width)<1,'series review close preserves video width');
 check(await page.getByRole('button',{name:'评论与互动',exact:true}).getAttribute('aria-pressed')==='true','comment tabs stay enabled after returning to selection');
 await page.getByRole('button',{name:'评论与互动',exact:true}).click();
 check(await page.getByRole('tab').allTextContents().then(x=>x.join('|')==='选集'),'bottom toggle on selection removes both enabled comment tabs');
 await page.getByRole('button',{name:'评论与互动',exact:true}).click();
 await page.evaluate(()=>changeEpisode());
 await page.getByRole('tab',{name:'选集',selected:true}).waitFor();
 const before=(await socialCalls()).length;
 await page.waitForTimeout(100);
 check((await socialCalls()).length===before,'new episode resets to selection and makes no social fetch');
 await page.evaluate(()=>{hold=true});
 const loadingBefore=(await socialCalls()).length;
 await page.getByRole('button',{name:'评论与互动',exact:true}).click();
 await page.waitForFunction(n=>calls.filter(c=>/comments|metrics|replies/.test(c.path)).length>=n+2,loadingBefore);
 await page.getByRole('button',{name:'评论与互动',exact:true}).click();
 const heldCount=(await socialCalls()).length;
 await page.getByRole('button',{name:'评论与互动',exact:true}).click();
 await page.waitForTimeout(80);
 check((await socialCalls()).length===heldCount&&await page.evaluate(()=>aborted===0),'closing and reopening while loading joins the same background requests');
 await page.getByRole('button',{name:'评论与互动',exact:true}).click();
 await page.evaluate(()=>{hold=false;releaseReads();});
 await page.waitForTimeout(80);
 await page.getByRole('button',{name:'评论与互动',exact:true}).click();
 await page.locator('.desktop-social-item').first().waitFor();
 check((await socialCalls()).length===heldCount,'background completion while hidden is cached for reopening');
 await page.getByRole('tab',{name:'整剧剧评',exact:true}).click();
 await page.getByText('series fixture',{exact:true}).waitFor();
 const seriesCount=(await socialCalls()).length;
 await page.getByRole('tab',{name:'本集评论',exact:true}).click();
 await page.getByRole('tab',{name:'整剧剧评',exact:true}).click();
 await page.getByText('series fixture',{exact:true}).waitFor();
 check((await socialCalls()).length===seriesCount,'switching comment tabs reuses each cached page');
 await page.evaluate(()=>{hold=true});
 await page.getByRole('button',{name:'刷新评论',exact:true}).click();
 await page.waitForFunction(n=>calls.filter(c=>/comments|metrics|replies/.test(c.path)).length>n,seriesCount);
 await page.getByRole('button',{name:'评论与互动',exact:true}).click();
 check(await page.getByRole('tab').allTextContents().then(x=>x.join('|')==='选集'),'closing a refresh hides both comment pages');
 await page.evaluate(()=>changeEpisode());
 await page.waitForFunction(()=>aborted>=1);
 check(await page.evaluate(()=>aborted>=1),'changing episode cancels old background requests');
 await page.evaluate(()=>{hold=false;failComments=true});
 await page.getByRole('button',{name:'评论与互动',exact:true}).click();
 await page.getByText('评论加载失败，请重试',{exact:false}).waitFor();
 check(await page.getByRole('button',{name:'重试',exact:true}).count()===1,'failed comments expose retry');
 await page.evaluate(()=>{failComments=false});
 await page.getByRole('button',{name:'重试',exact:true}).click();
 await page.locator('.desktop-social-item').first().waitFor();
 await page.getByRole('button',{name:'关闭评论页面',exact:true}).click();
 check(await page.locator('aside').isVisible(),'comment close after retry retains the right column');
 check(await page.getByRole('tab',{name:'选集',exact:true}).evaluate(n=>n===document.activeElement),'comment close after retry focuses selection');
 await page.getByRole('button',{name:'关闭右侧抽屉',exact:true}).click();
 check(await page.locator('aside').isHidden(),'selection still closes the complete drawer after loading and retry');
 await page.mouse.move(0,0);
 await page.getByRole('button',{name:'弹幕',exact:true}).focus();
 await page.getByRole('region',{name:'弹幕设置',exact:true}).waitFor();
 await page.getByRole('button',{name:'弹幕',exact:true}).click();
 await page.mouse.move(0,0);await page.waitForTimeout(350);
 check(await page.getByRole('button',{name:'弹幕',exact:true}).evaluate(node=>node===document.activeElement)&&await page.locator('.desktop-danmaku-panel').count()===0,'pointer leave closes mouse-focused toggle settings');
 await page.getByRole('button',{name:'弹幕',exact:true}).click();
 await page.mouse.move(0,0);await page.waitForTimeout(350);
 await page.locator('.player-mini-toggle').focus();
 await page.getByRole('button',{name:'弹幕',exact:true}).focus();
 await page.mouse.move(0,0);await page.waitForTimeout(350);
 check(await page.getByRole('region',{name:'弹幕设置',exact:true}).isVisible(),'keyboard focus keeps settings open after pointer leaves');
 check(await page.locator('.desktop-danmaku-panel input[type=range]').count()===4,'focus on same danmaku toggle exposes all settings without a shortcut');
 check(await page.locator('.desktop-danmaku-panel').evaluate(panel=>{
  const p=document.createElement('p');p.textContent='长'.repeat(300);panel.append(p);
  const ok=getComputedStyle(p).whiteSpace!=='nowrap'&&p.scrollWidth<=p.clientWidth+1;p.remove();return ok;
 }),'long settings text wraps inside the panel instead of inheriting toolbar nowrap');
 await page.keyboard.press('Tab');
 check(await page.getByRole('region',{name:'弹幕设置',exact:true}).isVisible(),'tabbing into settings keeps panel open');
 await page.getByRole('slider',{name:'移动速度',exact:true}).focus();
 await page.keyboard.press('End');
 check(await page.evaluate(()=>danmakuApi.settings().duration===4),'speed slider to the right means faster');
 await page.getByRole('button',{name:'恢复默认弹幕设置',exact:true}).click();
 check(await page.evaluate(()=>danmakuApi.settings().duration===14),'restore default duration is 14 seconds');
 check(await page.locator('textarea,input:not([type=range])').count()===0,'no comment or danmaku send field');
 await page.mouse.move(0,0); await page.waitForTimeout(300);
 for(const width of [1280,640,1600]){
  await page.setViewportSize({width,height:720}); await page.waitForTimeout(100);
  const boxes=await page.locator('.return-button,.desktop-selection-open,.player-mini-toggle,.window-controls button').evaluateAll(nodes=>nodes.map(n=>{const r=n.getBoundingClientRect();return {name:n.textContent,left:r.left,right:r.right,top:r.top,bottom:r.bottom};}));
  check(boxes.every((a,i)=>a.left>=0&&a.right<=width&&boxes.slice(i+1).every(b=>Math.min(a.right,b.right)<=Math.max(a.left,b.left)||Math.min(a.bottom,b.bottom)<=Math.max(a.top,b.top))),`all individual top controls avoid overlap at ${width}px`);
 }
 await page.locator('.player-mini-toggle').evaluate(node=>node.style.width='96px');
 await page.waitForTimeout(100);
 const miniBox=await page.locator('.player-mini-toggle').boundingBox(),selectionBox=await page.locator('.desktop-selection-open').boundingBox();
 check(selectionBox.x+selectionBox.width+8<=miniBox.x,'mini button width changes update selection offset without resizing the window');
 await page.locator('.player-chrome').evaluate(node=>node.style.height='120px');
 await page.waitForTimeout(100);
 check(await page.locator('.desktop-danmaku').evaluate(layer=>Math.abs(layer.getBoundingClientRect().bottom-layer.parentElement.querySelector('.player-chrome').getBoundingClientRect().top)<1),'DOM danmaku inset follows a taller actual control band');
 await page.locator('.player-chrome').evaluate(node=>{node.style.height='50px';});await page.waitForTimeout(100);
 check(await page.locator('.desktop-danmaku').evaluate(layer=>Math.abs(layer.getBoundingClientRect().bottom-layer.parentElement.querySelector('.player-chrome').getBoundingClientRect().top)<1),'DOM danmaku inset follows a shorter control band');
 await page.locator('.player-chrome').evaluate(node=>node.style.opacity='0');await page.waitForTimeout(100);
 check(await page.locator('.player-chrome').evaluate(node=>getComputedStyle(node).opacity==='1'),'open settings keep their host controls visible');
 await page.getByRole('button',{name:'关闭弹幕设置',exact:true}).click();await page.waitForTimeout(100);
 check(await page.locator('.desktop-danmaku').evaluate(layer=>Math.abs(layer.getBoundingClientRect().bottom-layer.parentElement.getBoundingClientRect().bottom)<1),'hidden control band returns all space to DOM danmaku');
 await page.locator('.player-chrome').evaluate(node=>{node.style.removeProperty('height');node.style.removeProperty('opacity');});
 // Respect the host keyboard owner: the module does not prevent or stop events.
 await page.evaluate(()=>{window.keySeen=0;window.addEventListener('keydown',()=>keySeen++);});
 await page.keyboard.press('Escape');
 check(await page.evaluate(()=>keySeen===1),'original keyboard handler still receives Escape');
 check(errors.length===0,'no browser exceptions: '+errors.join(';'));
 console.log(`PASS ${count} composition checks`);
}finally{await browser?.close();await new Promise(r=>server.close(r));}
