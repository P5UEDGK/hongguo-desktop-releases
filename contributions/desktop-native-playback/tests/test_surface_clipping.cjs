const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[2]||path.join(__dirname,'../src/frontend-native.js'),'utf8');
const context={Number,Math,Set,window:{devicePixelRatio:1,innerWidth:800,innerHeight:600},document:{hidden:false}};
vm.createContext(context);vm.runInContext(source.slice(0,source.indexOf('function desktopNativePlayback(')),context);
const rect={left:-100,top:-50,width:800,height:600},media={getBoundingClientRect:()=>rect,closest:()=>({querySelector:()=>null})};
assert(context.desktopNativeSurfaceVisible(media));assert.deepEqual(Array.from(context.desktopNativeSurfaceRect(media)),[-100,-50,800,516],'partial viewport keeps the original child geometry for parent clipping');
for(const patch of [{left:-900,top:0},{left:0,top:-700},{left:900,top:0},{left:0,top:700}]){Object.assign(rect,patch);assert.equal(context.desktopNativeSurfaceVisible(media),false,'fully offscreen video must hide its native surface');}
console.log('PASS negative child geometry and full viewport exclusion');
