const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(require('node:path').join(__dirname,'../src/native-controls.mjs'),'utf8').replaceAll('export function','function');
const settle=async()=>{for(let i=0;i<25;i++)await new Promise(setImmediate)};
function fixture(open,decode=()=>Promise.resolve()){
  let paintReads=0,interval,cleared=false,disconnected=false;
  const sent=[],layout=[],media={};
  const element=()=>({className:'',style:{cssText:'',setProperty(){}},append(){},setAttribute(){},
    querySelectorAll:()=>[],closest:()=>null,cloneNode(){return element()}});
  const chrome=element();chrome.getBoundingClientRect=()=>({top:70,height:30});
  const stage={className:'player-stage',getBoundingClientRect:()=>({width:10,height:100,top:0}),
    querySelector(selector){paintReads++;return selector==='.player-chrome'?chrome:null;}};
  const context={Number,Math,Uint8Array,Response,Blob,CompressionStream,btoa,unescape,encodeURIComponent,
    devicePixelRatio:1,getComputedStyle:()=>({getPropertyValue:()=>''}),
    XMLSerializer:class{serializeToString(){return '<div>fixture</div>'}},
    Image:class{decode(){return decode()}},HTMLInputElement:class{},HTMLSelectElement:class{},
    MutationObserver:class{observe(){}disconnect(){disconnected=true}},
    setInterval(fn){interval=fn;return 1},clearInterval(){cleared=true},
    document:{hidden:false,head:{},styleSheets:[],createElement(name){
      if(name==='canvas')return {getContext:()=>({clearRect(){},drawImage(){},
        getImageData:()=>({data:new Uint8ClampedArray(10*30*4).fill(128)})})};
      return element();
    }}};
  vm.createContext(context);vm.runInContext(source,context);
  const painter=context.desktopNativeControlsOverlay(media,stage,v=>sent.push(v),()=>layout.push(true),()=>open.value);
  return {painter,sent,layout,media,tick:()=>interval(),reads:()=>paintReads,disposed:()=>cleared&&disconnected};
}
(async()=>{
  const open={value:false},f=fixture(open);
  await settle();assert.equal(f.reads(),0,'handoff must not clone or rasterize controls before presentation is ready');
  assert.equal(f.painter.ready,false);assert.equal(f.sent.length,0);
  open.value=true;await f.tick();await settle();
  assert.equal(f.sent.length,1,f.media.desktopControlsOverlayError);assert.equal(f.painter.ready,true);assert(f.sent[0].controlsOverlay.data);
  const reads=f.reads();open.value=false;
  assert.equal(f.painter.ready,false,'critical window must reveal live HTML controls through the existing clipping path');
  await f.tick();assert.equal(f.reads(),reads);assert.equal(f.sent.length,1);
  open.value=true;await f.tick();assert.equal(f.sent.length,1,'unchanged image is not uploaded twice');
  f.painter.dispose();assert(f.disposed());

  let resolve;const pending=new Promise(r=>resolve=r),gate={value:true};
  const late=fixture(gate,()=>pending);await settle();gate.value=false;resolve();await settle();
  assert.equal(late.sent.length,0,'a decode started earlier must not paint into the handoff window');
  gate.value=true;await late.tick();await settle();assert.equal(late.sent.length,1);
  late.painter.dispose();
  console.log('PASS: deferred raster, live HTML fallback gate, late-decode cancellation, deduplication and cleanup');
})().catch(e=>{console.error(e);process.exitCode=1});
