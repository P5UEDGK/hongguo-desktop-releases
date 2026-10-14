// Verify the shared season owner in a decoded installation resource.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(process.argv[2],'utf8');
const queries=source.indexOf('function seasonSearchQueries(');
const parser=source.lastIndexOf('function Ts(',queries);
const start=source.lastIndexOf('const jl=',parser);
const end=source.indexOf('async function KR(',queries);
assert(start>=0&&parser>start&&end>queries,'Installed season owner boundaries missing');
const context=vm.createContext({});
vm.runInContext(source.slice(start,end),context);
const parse=vm.runInContext('Ts',context),search=vm.runInContext('seasonSearchQueries',context);
for(let season=1;season<=12;season++) {
  const title=`凡尘问道（第${season}季）`,result=parse(title);
  assert.equal(result?.base,'凡尘问道');assert.equal(result?.season,season);
  assert.equal(result?.explicit,true);assert.equal(JSON.stringify(search(title)),JSON.stringify(['凡尘问道']));
}
for(const title of ['凡尘问道（第1季)','凡尘问道(第1季）','凡尘问道（第1季','凡尘问道（第0季）'])assert.equal(parse(title),null,title);
assert.equal(parse('凡尘问道(第十二季)').season,12);
assert.equal(parse('凡尘问道（第２季）').season,2);
assert.equal(parse('原始？副题第40季').base,'原始？副题');
console.log('PASS installed season owner: 12 original titles, paired parentheses, Chinese/fullwidth numbers, malformed suffixes and punctuation');
