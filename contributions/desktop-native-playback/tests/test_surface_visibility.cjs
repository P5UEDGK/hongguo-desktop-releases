const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[2]||path.join(__dirname,'../src/frontend-native.js'),'utf8');
const ancestor={},stage={parentElement:ancestor},media={parentElement:stage,closest:()=>stage,getBoundingClientRect:()=>({width:800,height:600})};
const styles=new Map(),context={document:{hidden:false},getComputedStyle:node=>styles.get(node)||{},window:{},Math};
vm.createContext(context);vm.runInContext(source,context);
for(const target of [media,stage,ancestor])for(const style of [{visibility:'hidden'},{visibility:'collapse'},{opacity:'0'},{opacity:'0.0'},{display:'none'}]){
 styles.set(target,style);assert.equal(context.desktopNativeSurfaceVisible(media),false,'CSS-hidden video and ancestors hide native window');styles.clear();
}
assert.equal(context.desktopNativeSurfaceVisible(media),true);context.document.hidden=true;assert.equal(context.desktopNativeSurfaceVisible(media),false);
context.document.hidden=false;media.getBoundingClientRect=()=>({width:0,height:600});assert.equal(context.desktopNativeSurfaceVisible(media),false);
// Check the real layout closure and standby activation gate use the same predicate.
assert(source.includes('const visible = desktopNativeSurfaceVisible(media)'));
if(source.includes('const canShow ='))assert(/const canShow = \(\) => desktopNativeSurfaceVisible\(media\)/.test(source));
console.log('PASS CSS surface visibility includes ancestor opacity and standby activation');
