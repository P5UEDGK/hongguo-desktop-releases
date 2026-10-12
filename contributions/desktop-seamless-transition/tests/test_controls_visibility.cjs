const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const context = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/frontend-controls.js'), 'utf8'), context);
const reveal = context.desktopControlsShouldReveal;
let checks = 0;
function check(event, media, state, expected, reason) {
  assert.equal(reveal(event, media, state), expected, reason);
  checks++;
}
// Source disposal has reset ended before the controls' ended listener runs.
check({type:'ended'}, {paused:true, ended:false}, {autoContinue:true}, false, 'EOF event survives teardown');
check({type:'pause'}, {paused:true, ended:true}, {autoContinue:true}, false, 'EOF-related pause stays hidden');
check({type:'ended'}, {paused:true, ended:false}, {autoContinue:false}, true, 'last episode remains operable');
check({type:'pause'}, {paused:true, ended:false}, {}, true, 'ordinary user pause reveals');
for (const type of ['pause', 'ended']) {
  check({type}, {paused:true, ended:false}, {transitioning:true}, false, 'selection/loading does not reveal');
  check({type}, {paused:true, ended:false}, {disabled:true}, false, 'disabled controls retain visibility');
}
for (const type of ['play', 'playing', 'timeupdate', 'loadedmetadata', 'durationchange', 'progress']) {
  check({type}, {paused:true}, {}, false, 'ordinary synchronization does not reveal');
}
check(undefined, {paused:true}, {}, false, 'initial sync retains inherited state');
check({type:'pause'}, null, {}, false, 'released element is safe');
check({type:'pause'}, {paused:false}, {}, false, 'stale pause does not reveal a playing element');
check({type:'pause'}, {paused:true, ended:false}, {transitioning:false, autoContinue:true}, true, 'user pause still works with auto-next');
console.log(`PASS: ${checks} controls visibility checks`);
