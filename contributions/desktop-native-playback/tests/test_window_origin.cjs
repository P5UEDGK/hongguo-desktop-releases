const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const context={Number,Array};vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/frontend-codec.js'),'utf8'),context);
const accept=context.desktopAcceptWindowOrigin;
const complete={windowOrigin:0,duration:60,state:'complete',playlistReady:true,playableRange:[0,60]};
assert(accept(complete,25),'restored complete cache uses its actual zero origin');
assert(accept({...complete,windowOrigin:25,state:'preparing',playlistReady:false,playableRange:[25,30]},25));
for(const row of [{...complete,state:'preparing'},{...complete,playlistReady:false},{...complete,playableRange:[0,59]},
  {...complete,playableRange:[1,60]},{...complete,playableRange:null},{...complete,windowOrigin:10},
  {...complete,windowOrigin:-1},{...complete,windowOrigin:NaN},{...complete,windowOrigin:60},
  {...complete,duration:Infinity},{...complete,duration:0}])assert.equal(accept(row,25),false,JSON.stringify(row));
assert(accept({windowOrigin:0,duration:0,state:'preparing'},0),'unknown duration still permits an ordinary matching origin');
assert(accept({windowOrigin:25,duration:null,state:'preparing'},25));
assert.equal(accept(complete,-1),false);
console.log('PASS: complete cache origin zero is accepted only with full committed coverage; ordinary window bounds remain strict');
