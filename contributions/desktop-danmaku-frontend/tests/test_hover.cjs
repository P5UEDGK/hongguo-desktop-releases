const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const files=[path.join(__dirname,'../src/danmaku.mjs')];
for(const file of files){
 const source=fs.readFileSync(file,'utf8');
 const start=source.indexOf('function DesktopDanmakuSettings('),end=source.indexOf('function desktopUniqueDanmaku(',start);
 assert(start>=0&&end>start);
 const timers=[],changes=[];class TestNode{}
 const context={Node:TestNode,setTimeout:(fn,delay)=>(timers.push({fn,delay}),timers.length),clearTimeout(){},
  O:{useState:v=>[typeof v==='function'?v():v,x=>changes.push(x)],useRef:()=>({current:null}),useEffect(){},useLayoutEffect(){}},
  b:{jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})},
  desktopDanmakuSettings:()=>({opacity:80,lanes:3,fontSize:28,duration:14}),desktopSocialPreference:()=>true,desktopSocialSet(){}};
 vm.createContext(context);
 const component=vm.runInContext(source.slice(start,end)+';DesktopDanmakuSettings({media:{current:null},sessionKey:"test"})',context);
 const control={contains(value){assert(value instanceof TestNode);return true},getBoundingClientRect:()=>({left:10,right:50,top:10,bottom:50}),querySelector:()=>null};
 component.props.ref.current=control;
 component.props.onPointerEnter({clientX:20,clientY:20});assert.equal(changes.at(-1),true);
 // Native HWND boundaries can give React Window instead of a DOM Node.
 assert.doesNotThrow(()=>component.props.onPointerLeave({currentTarget:control,relatedTarget:{window:true}}));
 assert.equal(timers.at(-1).delay,1200);
 timers.at(-1).fn();assert.equal(changes.at(-1),true,'Native hover loss must preserve the stationary pointer');
 component.props.onPointerMove({clientX:80,clientY:80});
 component.props.onPointerLeave({currentTarget:control,relatedTarget:null});
 timers.at(-1).fn();assert.equal(changes.at(-1),false);
 const count=timers.length;
 component.props.onPointerLeave({currentTarget:control,relatedTarget:new TestNode});assert.equal(timers.length,count);
 component.props.onPointerLeave({currentTarget:control,relatedTarget:null});
 component.props.onPointerMove({clientX:20,clientY:20});changes.length=0;timers.at(-1).fn();assert.equal(changes.length,0);
 component.props.onPointerMove({clientX:80,clientY:80});changes.length=0;control.querySelector=()=>({});timers.at(-1).fn();assert.equal(changes.length,0);
 component.props.onFocusCapture();assert.equal(changes.at(-1),true);
 console.log('PASS: native Window/null/Node transitions, 1200ms grace, hover/focus hold:',path.basename(file));
}
