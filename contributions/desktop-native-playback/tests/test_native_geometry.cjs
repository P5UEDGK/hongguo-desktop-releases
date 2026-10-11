const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
let style={opacity:'1'},chrome={getBoundingClientRect:()=>({top:556,height:64})};
const stage={querySelector:()=>chrome};
const media={closest:()=>stage,getBoundingClientRect:()=>({left:10,top:20,width:800,height:600})};
const c={Math,window:{devicePixelRatio:1},getComputedStyle:()=>style};
vm.createContext(c);vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/frontend-native.js'),'utf8'),c);
const rect=()=>Array.from(c.desktopNativeSurfaceRect(media));
assert.deepEqual(rect(),[10,20,800,536]);
for(const hidden of [{opacity:'0'},{display:'none'},{visibility:'hidden'},{visibility:'collapse'}]){
  style=hidden;assert.deepEqual(rect(),[10,20,800,600],'hidden controls reclaim the whole video surface');
}
style={opacity:'.5'};assert.deepEqual(rect(),[10,20,800,536],'visible transition still protects controls');
chrome.hidden=true;assert.deepEqual(rect(),[10,20,800,600]);delete chrome.hidden;
style={opacity:'1'};c.window.devicePixelRatio=1.5;assert.deepEqual(rect(),[15,30,1200,804]);
chrome=null;c.window.devicePixelRatio=1;assert.deepEqual(rect(),[10,20,800,516]);
console.log('PASS: actual control visibility, transition, DPI and fallback native geometry');
