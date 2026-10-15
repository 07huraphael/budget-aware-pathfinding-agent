/* Run UI logic against the local API with a minimal DOM, without a browser dependency.
   This verifies behavior; it does not substitute for browser layout inspection. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
class Element {
  constructor(id="") { this.id=id;this.value="";this.children=[];this.disabled=false;this.checked=false;this.hidden=false;this.textContent="";this.className="";this.innerHTML="";this.classList={add(){},remove(){},contains(){return false},toggle(){}}; }
  append(...items) {this.children.push(...items);}
  appendChild(item) {this.children.push(item);return item;}
  replaceChildren(...items) {this.children=[...items];}
  getBoundingClientRect(){return {left:0,top:0,width:900,height:900};}
  getContext(){return new Proxy({}, {get:()=>()=>{},set:()=>true});}
}
const ids=["size","structure","seed","density","weighted","method","budget","error","run","generate","grid","speed","play","timeline","export","log","active","phase","remaining","expanded","cost","quality","position","reason","comparisons","runtime","memory","chart","mapSize","mapSeed","actualDensity","densityValue"];
const elements=Object.fromEntries(ids.map(id=>[id,new Element(id)]));
for(const [id,value] of Object.entries({size:"20",structure:"random",seed:"42",density:"20",method:"adaptive",budget:"1000",speed:"25"}))elements[id].value=value;
const sandbox={document:{getElementById:id=>elements[id],querySelectorAll:()=>[elements.run,elements.generate],createElement:()=>new Element(),body:new Element()},
  fetch:(url,options)=>fetch(`http://127.0.0.1:8765${url}`,options), console, setInterval:()=>1,clearInterval(){},Blob,URL};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync("src/budget_pathfinding/web/app.js","utf8"),sandbox);
async function waitForReady(){for(let i=0;i<100;i++){if(vm.runInContext("grid!==null",sandbox))return;await new Promise(resolve=>setTimeout(resolve,10));}throw Error("Initial map did not load");}
(async()=>{
  await waitForReady();
  assert.equal(elements.mapSize.textContent,"20 × 20");
  await elements.run.onclick();
  assert.ok(elements.comparisons.children.length>=4);
  assert.ok(elements.log.children.length>=2);
  vm.runInContext("pause();cursor=data.result.expansions;render()",sandbox);
  assert.notEqual(elements.active.textContent,"준비");
  assert.ok(elements.phase.textContent.includes("반환")||elements.phase.textContent.includes("미발견")||elements.phase.textContent.includes("없음"));
  const before=vm.runInContext("grid.walls.length",sandbox);
  elements.grid.onclick({clientX:45,clientY:45});
  assert.equal(Math.abs(vm.runInContext("grid.walls.length",sandbox)-before),1);
  assert.equal(elements.active.textContent,"준비");
  elements.structure.value="u";
  await elements.structure.onchange();
  await elements.run.onclick();
  vm.runInContext("pause();cursor=data.result.expansions;render()",sandbox);
  assert.equal(elements.phase.textContent,"경로 확보 · 반환");
  assert.ok(Number(elements.cost.textContent.replaceAll(",",""))>0);
  console.log("OK: UI initialization, API comparison, playback, wall editing, U-map search.");
})().catch(error=>{console.error(error);process.exitCode=1;});
