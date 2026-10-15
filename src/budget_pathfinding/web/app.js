"use strict";
const $ = id => document.getElementById(id);
const labels = {adaptive:"Adaptive", astar:"A*", weighted_3:"WA* · 3.0", "weighted_1.5":"WA* · 1.5", greedy:"Greedy", bfs:"BFS", dijkstra:"Dijkstra", ara:"ARA*", initial:"Initial only", equal:"Equal budget", no_progress:"No progress", no_early_return:"No early return", unlimited_switches:"Unlimited switches", first_solution:"First solution"};
let grid = null, data = null, cursor = 0, playing = false, timer = null, logCursor = -1;
const ctx = $("grid").getContext("2d");
const number = n => Number(n).toLocaleString("ko-KR");
function parameters() {return {size:Number($("size").value), density:Number($("density").value)/100, seed:Number($("seed").value), structure:$("structure").value, weighted:$("weighted").checked, method:$("method").value, budget:Number($("budget").value)};}
function error(message) {$("error").hidden = !message; $("error").textContent = message || "";}
async function request(payload) {
  error(null); document.body.classList.add("busy");
  const controls=Array.from(document.querySelectorAll(".controls input, .controls select, .controls button"));
  controls.forEach(element=>element.disabled=true);
  try {const response = await fetch("/api/run", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)}); const result = await response.json(); if(!response.ok) throw new Error(result.error); return result;}
  finally {document.body.classList.remove("busy"); controls.forEach(element=>element.disabled=false);}
}
function pause() {playing = false; clearInterval(timer); timer = null; $("play").textContent = "▶";}
function reset() {pause(); data=null;cursor=0;logCursor=-1;$("play").disabled=$("timeline").disabled=$("export").disabled=true;$("log").innerHTML='<div class="empty">실행하면 판단 기록이 표시됩니다.</div>';$("active").textContent="준비";$("phase").textContent="탐색을 실행해 주세요";$("remaining").textContent=number($("budget").value);$("expanded").textContent="0 nodes used";$("cost").textContent="—";$("quality").textContent="품질은 실행 후 평가";$("position").textContent="0 / 0";$("timeline").value=0;$("reason").textContent="지도 특징과 남은 예산을 바탕으로 초기 전략을 선택합니다.";$("comparisons").innerHTML='<tr><td colspan="5" class="empty">실행 후 같은 지도에서 비교합니다.</td></tr>';$("runtime").textContent="계산 시간 —";$("memory").textContent="메모리: 실행 후 추정";chart();}
function setGrid(next) {grid=next;$("mapSize").textContent=`${grid.width} × ${grid.height}`;$("mapSeed").textContent=`seed ${grid.seed}`;$("actualDensity").textContent=`실제 밀도 ${(grid.walls.length/(grid.width*grid.height)*100).toFixed(1)}%`;draw();}
function cellKey(cell) {return cell.join(",");}
function draw() {
  if(!grid) return;
  const canvas=$("grid"), size=900/grid.width, height=900/grid.height, gap=grid.width>50?0.8:1.8;
  ctx.fillStyle="#0e1824";ctx.fillRect(0,0,900,900);
  const walls=new Set(grid.walls.map(cellKey)), visited=new Map();
  if(data) for(let i=0;i<Math.min(cursor,data.result.trace.length);i++) {const e=data.result.trace[i];visited.set(cellKey(e.cell), e.strategy);}
  for(let y=0;y<grid.height;y++) for(let x=0;x<grid.width;x++) {
    const key=`${x},${y}`, cost=grid.costs[y][x];
    ctx.fillStyle=walls.has(key)?"#607086":visited.has(key)?(visited.get(key)===data.result.initial_strategy?"#365d83":"#555887"):cost===5?"#55405a":cost===3?"#3c354c":"#1c2a3a";
    ctx.fillRect(x*size+gap/2,y*height+gap/2,size-gap,height-gap);
  }
  let path=null;
  if(data) for(const improvement of data.result.improvements) if(improvement.expansions<=cursor) path=improvement.path;
  if(path) {ctx.strokeStyle="#a7f9d5";ctx.lineWidth=Math.max(2,size*.17);ctx.lineJoin="round";ctx.lineCap="round";ctx.beginPath();path.forEach((c,i)=>i?ctx.lineTo((c[0]+.5)*size,(c[1]+.5)*height):ctx.moveTo((c[0]+.5)*size,(c[1]+.5)*height));ctx.stroke();}
  for(const [cell,color,letter] of [[grid.start,"#69e4b5","S"],[grid.goal,"#ffba73","G"]]) {ctx.fillStyle=color;ctx.fillRect(cell[0]*size+gap/2,cell[1]*height+gap/2,size-gap,height-gap);if(grid.width<=50){ctx.fillStyle="#14242c";ctx.font=`bold ${size*.5}px sans-serif`;ctx.textAlign="center";ctx.textBaseline="middle";ctx.fillText(letter,(cell[0]+.5)*size,(cell[1]+.5)*height);}}
}
function render() {
  if(!data) return draw();
  const r=data.result, complete=cursor>=r.expansions;
  let decision=r.decisions[0], decisionIndex=0;
  r.decisions.forEach((e,i)=>{if(e.expansions<=cursor && (e.action!=="return"||complete)){decision=e;decisionIndex=i;}});
  const improvement=[...r.improvements].reverse().find(e=>e.expansions<=cursor);
  $("active").textContent=labels[decision.strategy]||decision.strategy;
  $("phase").textContent=complete?(r.status==="success"?"경로 확보 · 반환":r.status==="no_path"?"경로 없음 확인":"예산 내 미발견"):"탐색 기록 재생 중";
  $("remaining").textContent=number(r.budget.expansions-cursor);$("expanded").textContent=`${number(cursor)} nodes used`;
  $("cost").textContent=improvement?number(improvement.cost):"—";
  $("quality").textContent=improvement&&data.optimal_cost_evaluation_only?`C/C* = ${(improvement.cost/data.optimal_cost_evaluation_only).toFixed(3)} · 사후 평가`:"경로를 확보하는 중";
  $("reason").textContent=decision.reason;$("position").textContent=`${number(cursor)} / ${number(r.expansions)}`;$("timeline").value=cursor;
  if(logCursor!==decisionIndex) {Array.from($("log").children).forEach((item,i)=>item.classList.toggle("future",i>decisionIndex));logCursor=decisionIndex;}
  draw();chart();
}
function chart() {
  const svg=$("chart"), points=data?data.result.improvements.filter(e=>e.expansions<=cursor):[];
  let markup='<line x1="35" y1="135" x2="290" y2="135" stroke="#35445a"/><line x1="35" y1="25" x2="35" y2="135" stroke="#35445a"/><text x="35" y="155" fill="#8f9db1" font-size="10">0</text>';
  if(!points.length) {svg.innerHTML=markup+'<text x="160" y="80" text-anchor="middle" fill="#8f9db1" font-size="11">첫 경로를 기다리는 중</text>';return;}
  const max=Math.max(...points.map(e=>e.cost))*1.1, min=Math.max(0,Math.min(...points.map(e=>e.cost))*.8), cap=Math.max(1,data.result.budget.expansions);
  const x=e=>35+e.expansions/cap*255, y=e=>135-(e.cost-min)/(max-min)*105;
  let d=`M ${x(points[0])} ${y(points[0])}`;
  for(let i=1;i<points.length;i++) d+=` H ${x(points[i])} V ${y(points[i])}`;
  d+=` H ${35+cursor/cap*255}`;
  markup+=`<path d="${d}" fill="none" stroke="#69e4b5" stroke-width="2"/><text x="290" y="155" text-anchor="end" fill="#8f9db1" font-size="10">${number(cap)}</text>`;
  for(const e of points) markup+=`<circle cx="${x(e)}" cy="${y(e)}" r="3" fill="#69e4b5"/><text x="${x(e)}" y="${y(e)-9}" text-anchor="middle" fill="#d7f9ed" font-size="10">${e.cost}</text>`;
  svg.innerHTML=markup;
}
async function generate(increment=false) {try {if(increment) $("seed").value=Number($("seed").value)+1;reset();const result=await request({...parameters(),generate_only:true});setGrid(result.grid);}catch(e){error(e.message);}}
$("run").onclick=async()=>{try {pause();const result=await request({...parameters(),grid});reset();data=result;setGrid(result.grid);const r=data.result;$("timeline").max=Math.max(1,r.expansions);$("play").disabled=$("timeline").disabled=$("export").disabled=false;$("runtime").textContent=`전체 계산 ${(r.elapsed_seconds*1000).toFixed(2)} ms`;$("memory").textContent=`보존 상태 추정 ${(r.peak_retained_estimate_bytes/1024).toFixed(1)} KB · 전환 ${r.switches}회 · 중복 ${r.duplicate_expansions} nodes`;
  $("comparisons").replaceChildren();for(const item of data.comparisons){const row=document.createElement("tr");if(item.method===r.method) row.className="selected-row";const values=[labels[item.method]||item.method,item.status==="success"?"경로 확보":item.status==="no_path"?"경로 없음":"미발견",item.cost===null?"—":number(item.cost),number(item.expansions),`${(item.seconds*1000).toFixed(2)} ms`];values.forEach((v,i)=>{const cell=document.createElement("td");cell.textContent=v;if(i===1)cell.className=item.status==="success"?"success":"failure";row.appendChild(cell);});$("comparisons").appendChild(row);}
  $("log").replaceChildren();r.decisions.forEach(e=>{const item=document.createElement("div");item.className=`log-item ${e.action}`;const head=document.createElement("div");head.className="log-head";const label=document.createElement("span");label.textContent={select:"초기 선택",keep:"유지",switch:"전환",return:"반환"}[e.action];const count=document.createElement("small");count.textContent=`${number(e.expansions)} nodes`;head.append(label,count);const reason=document.createElement("p");reason.textContent=e.reason;item.append(head,reason);item.onclick=()=>{pause();cursor=e.expansions;render();};$("log").appendChild(item);});cursor=0;render();startPlayback();
}catch(e){error(e.message);}};
function startPlayback(){if(!data)return;if(cursor>=data.result.expansions)cursor=0;playing=true;$("play").textContent="Ⅱ";timer=setInterval(()=>{cursor=Math.min(data.result.expansions,cursor+Number($("speed").value));render();if(cursor>=data.result.expansions)pause();},60);}
$("play").onclick=()=>playing?pause():startPlayback();$("timeline").oninput=()=>{pause();cursor=Number($("timeline").value);render();};$("generate").onclick=()=>generate(true);
for(const id of ["size","structure","weighted","seed"]) $(id).onchange=()=>generate();
$("density").oninput=()=>{$("densityValue").textContent=`${$("density").value}%`;};$("density").onchange=()=>generate();
$("budget").onchange=()=>{if(!data)$("remaining").textContent=number($("budget").value);};
$("grid").onclick=e=>{if(!grid||document.body.classList.contains("busy"))return;const rect=$("grid").getBoundingClientRect(),cell=[Math.floor((e.clientX-rect.left)/rect.width*grid.width),Math.floor((e.clientY-rect.top)/rect.height*grid.height)],key=cellKey(cell);if([grid.start,grid.goal].some(c=>cellKey(c)===key))return;const existing=grid.walls.findIndex(c=>cellKey(c)===key);if(existing>=0)grid.walls.splice(existing,1);else grid.walls.push(cell);grid.structure="custom";reset();setGrid(grid);};
$("export").onclick=()=>{if(!data)return;const blob=new Blob([JSON.stringify(data,null,2)],{type:"application/json"}),url=URL.createObjectURL(blob),link=document.createElement("a");link.href=url;link.download=`pathfinding-${grid.seed}-${data.result.method}.json`;link.click();URL.revokeObjectURL(url);};
generate();
