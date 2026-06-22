#!/usr/bin/env python3
"""Regenerate Dashboard from scored day1_results.json"""
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs-binyu"
RESULTS = OUT / "day1_results.json"

with open(RESULTS, encoding="utf-8") as f:
    results = json.load(f)

# Build model stats
import statistics

tasks_map = {}
for r in results:
    tid = r["task"]["id"]
    tasks_map.setdefault(tid, {"id": tid, "title": r["task"]["title"], "type": r["task"]["type"]})

models_map = {}
for r in results:
    label = r["model"]["label"]
    models_map.setdefault(label, {"label": label, "items": []})
    models_map[label]["items"].append(r)

sorted_models = []
for label, m in sorted(models_map.items()):
    items = m["items"]
    scores = [r["score"] for r in items]
    lats = [r["output"]["latency"] for r in items if r["ok"]]
    toks = [r["output"]["usage"].get("total_tokens", 0) for r in items if r["ok"]]
    sorted_models.append({
        "label": label,
        "avg_score": round(statistics.mean(scores), 2) if scores else 0,
        "avg_latency": round(statistics.mean(lats), 2) if lats else 0,
        "avg_tokens": round(statistics.mean(toks), 1) if toks else 0,
    })
sorted_models.sort(key=lambda x: x["avg_latency"])

data_json = json.dumps(results, ensure_ascii=False)
models_json = json.dumps(sorted_models, ensure_ascii=False)
now_str = datetime.now().isoformat(timespec="seconds")

html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>论文速读能力评测 国产大模型对比</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
:root{{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#c9d1d9;--g5:#1b5e20;--g4:#4caf50;--g3:#ff9800;--g2:#e65100;--g1:#c62828;--gr:#555}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,sans-serif;line-height:1.55}}
header{{background:var(--card);border-bottom:1px solid var(--border);padding:24px;text-align:center}}
header h1{{font-size:24px;margin-bottom:4px}} header p{{color:#8b949e;font-size:13px}}
main{{max-width:1200px;margin:0 auto;padding:16px}}
.kpi-row{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}}
.kpi{{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:16px;text-align:center}}
.kpi .n{{font-size:34px;font-weight:700}} .kpi .l{{color:#8b949e;font-size:12px;margin-top:4px}} .kpi .warn{{color:#f44336}}
section{{margin-bottom:16px}}
.sh{{background:var(--card);border:1px solid var(--border);border-radius:8px 8px 0 0;padding:12px 16px;font-size:16px;font-weight:700;cursor:pointer;user-select:none}}
.sb{{background:var(--card);border:1px solid var(--border);border-top:0;border-radius:0 0 8px 8px;padding:16px;overflow-x:auto}}
.sb.hide{{display:none}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
td,th{{border:1px solid var(--border);padding:8px 10px;text-align:center}}
th{{background:#1c2129;font-weight:600;white-space:nowrap}}
.s5{{background:var(--g5);color:#fff}} .s4{{background:var(--g4);color:#000}} .s3{{background:var(--g3);color:#000}} .s2{{background:var(--g2);color:#fff}} .s1{{background:var(--g1);color:#fff}} .sp{{background:var(--gr);color:#aaa}}
.chart-box{{max-width:550px;margin:0 auto}}
.g2{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
.g3{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}
.card{{background:#1c2129;border:1px solid var(--border);border-radius:6px;padding:10px;font-size:13px}}
pre{{white-space:pre-wrap;font-size:12px;max-height:280px;overflow-y:auto;background:#111;padding:8px;border-radius:4px;margin-top:6px}}
.green{{color:#4caf50}} .red{{color:#f44336}} .gray{{color:#8b949e}}
footer{{text-align:center;color:#8b949e;font-size:11px;padding:16px;border-top:1px solid var(--border);margin-top:16px}}
@media(max-width:768px){{.kpi-row{{grid-template-columns:repeat(2,1fr)}} .g2,.g3{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<header><h1>论文速读能力评测 国产大模型对比</h1><p>SiliconFlow API 真实调用 · 5模型 x 7任务 · <span id="tc">-</span> 次调用 · {now_str}</p></header>
<main>
<div class="kpi-row" id="kpi"></div>

<section>
<div class="sh" onclick="this.nextElementSibling.classList.toggle('hide')">评分热力矩阵 <span style="float:right">-</span></div>
<div class="sb" id="matrix"></div>
</section>

<section>
<div class="sh" onclick="this.nextElementSibling.classList.toggle('hide')">雷达图：文本任务能力对比 <span style="float:right">-</span></div>
<div class="sb"><div class="chart-box"><canvas id="radar"></canvas></div></div>
</section>

<section>
<div class="sh" onclick="this.nextElementSibling.classList.toggle('hide')">性能对比 <span style="float:right">-</span></div>
<div class="sb">
<div class="g3" id="perf"></div>
<div class="g2" style="margin-top:12px">
<div class="chart-box"><canvas id="latBar"></canvas></div>
<div class="chart-box"><canvas id="tokBar"></canvas></div>
</div>
</div>
</section>

<section>
<div class="sh" onclick="this.nextElementSibling.classList.toggle('hide')">幻觉检测专项 <span style="float:right">-</span></div>
<div class="sb" id="hall"></div>
</section>

<section>
<div class="sh" onclick="this.nextElementSibling.classList.toggle('hide')">多模态专区 <span style="float:right">-</span></div>
<div class="sb" id="multi"></div>
</section>

<section>
<div class="sh" onclick="this.nextElementSibling.classList.toggle('hide')">路由建议 <span style="float:right">-</span></div>
<div class="sb" id="route"></div>
</section>
</main>
<footer>SiliconFlow API · 评分: 准确性/完整性/诚实性 · 文本与多模态分开路由</footer>

<script>
var D = {data_json};
var sortedModels = {models_json};

(function(){{
document.getElementById("tc").textContent = D.length;

var tasks = [...new Set(D.map(function(r){{return r.task.id;}}))];
var taskNames = {{}}; D.forEach(function(r){{taskNames[r.task.id]=r.task.title;}});
var models = sortedModels.map(function(m){{return m.label;}});
var okCount = D.filter(function(r){{return r.ok;}}).length;
var failCount = D.filter(function(r){{return !r.ok;}}).length;
var failReasons = D.filter(function(r){{return !r.ok;}}).map(function(r){{
 var m = r.output.text||""; return m.indexOf("timeout")>=0||m.indexOf("Timeout")>=0?"Timeout":m.indexOf("VLM")>=0?"Not VLM":"Other";
}});
var frCount = {{}}; failReasons.forEach(function(r){{frCount[r]=(frCount[r]||0)+1;}});
var frStr = Object.keys(frCount).map(function(k){{return k+":"+frCount[k];}}).join(", ");
document.getElementById("kpi").innerHTML =
 "<div class='kpi'><div class='n'>"+models.length+"</div><div class='l'>模型</div></div>"+
 "<div class='kpi'><div class='n'>"+tasks.length+"</div><div class='l'>任务 (5T+2M)</div></div>"+
 "<div class='kpi'><div class='n'>"+D.length+"</div><div class='l'>总调用 ("+okCount+" OK)</div></div>"+
 "<div class='kpi'><div class='n"+(failCount>0?" warn":"")+"'>"+failCount+"</div><div class='l'>失败 ("+frStr+")</div></div>";

// Matrix
var textTasks = ["paper_summary_001","paper_methods_002","paper_translate_003","paper_scenario_004","paper_hallucination_005"];
var multiTasks = ["multimodal_arch_006","multimodal_error_007"];
var allTasks = textTasks.concat(multiTasks);
var h = "<table><tr><th>模型</th>";
allTasks.forEach(function(t){{h+="<th>"+taskNames[t].substring(0,6)+"</th>";}});
h+="<th>均分</th></tr>";
models.forEach(function(m){{
 h+="<tr><th>"+m+"</th>";
 var scores = [];
 allTasks.forEach(function(t){{
  var r = D.find(function(x){{return x.model.label===m && x.task.id===t;}});
  if(!r){{h+="<td>-</td>";return;}}
  if(!r.ok){{h+="<td class='s1'>FAIL</td>";scores.push(0);return;}}
  var s = r.score;
  scores.push(s);
  var cls = s>=5?"s5":s>=4?"s4":s>=3?"s3":s>=2?"s2":s>=1?"s1":"sp";
  h+="<td class='"+cls+"'>"+(s>=0?s:"?")+"</td>";
 }});
 var avg = scores.length?(scores.reduce(function(a,b){{return a+b;}},0)/scores.length).toFixed(1):"-";
 h+="<td><b>"+avg+"</b></td></tr>";
}});
h+="</table>";
document.getElementById("matrix").innerHTML = h;

// Radar
var ctx = document.getElementById("radar").getContext("2d");
var colors = ["#4caf50","#2196f3","#ff9800","#9c27b0","#f44336"];
new Chart(ctx,{{
 type:"radar",
 data:{{
  labels:textTasks.map(function(t){{return taskNames[t].substring(0,8);}}),
  datasets:models.map(function(m,i){{return{{
   label:m,
   data:textTasks.map(function(t){{var r=D.find(function(x){{return x.model.label===m&&x.task.id===t;}});return r&&r.ok?r.score:0;}}),
   borderColor:colors[i%5],backgroundColor:colors[i%5]+"33",pointRadius:3
  }};}})
 }},
 options:{{scales:{{r:{{beginAtZero:true,max:5,ticks:{{color:"#c9d1d9"}},grid:{{color:"#30363d"}},pointLabels:{{color:"#c9d1d9"}}}}}},plugins:{{legend:{{labels:{{color:"#c9d1d9"}}}}}}}}
}});

// Performance
document.getElementById("perf").innerHTML = sortedModels.map(function(m){{
 var tier = m.avg_latency<15?"经济型":m.avg_latency<60?"均衡型":"重型";
 return "<div class='card'><b>"+m.label+"</b><br>延迟: "+m.avg_latency+"s | Token: "+m.avg_tokens+"<br>"+tier+"</div>";
}}).join("");

// Latency chart
var lctx = document.getElementById("latBar").getContext("2d");
new Chart(lctx,{{
 type:"bar",
 data:{{labels:allTasks.map(function(t){{return taskNames[t].substring(0,6);}}),datasets:models.map(function(m,i){{return{{label:m,data:allTasks.map(function(t){{var r=D.find(function(x){{return x.model.label===m&&x.task.id===t;}});return r&&r.ok?r.output.latency:0;}}),backgroundColor:colors[i%5]+"88"}};}})}},
 options:{{scales:{{y:{{title:{{display:true,text:"秒",color:"#c9d1d9"}},ticks:{{color:"#c9d1d9"}},grid:{{color:"#30363d"}}}},x:{{ticks:{{color:"#c9d1d9"}}}}}},plugins:{{legend:{{labels:{{color:"#c9d1d9"}}}}}}}}
}});

// Token chart
var tctx = document.getElementById("tokBar").getContext("2d");
new Chart(tctx,{{
 type:"bar",
 data:{{labels:models,datasets:[{{label:"Avg Tokens",data:models.map(function(m){{var toks=D.filter(function(r){{return r.model.label===m&&r.ok;}}).map(function(r){{return r.output.usage?r.output.usage.total_tokens:0;}});return toks.length?Math.round(toks.reduce(function(a,b){{return a+b;}},0)/toks.length):0;}}),backgroundColor:"#ff980088"}}]}},
 options:{{scales:{{y:{{title:{{display:true,text:"tokens",color:"#c9d1d9"}},ticks:{{color:"#c9d1d9"}},grid:{{color:"#30363d"}}}},x:{{ticks:{{color:"#c9d1d9"}}}}}},plugins:{{legend:{{labels:{{color:"#c9d1d9"}}}}}}}}
}});

// Hallucination
var hallR = D.filter(function(r){{return r.task.id==="paper_hallucination_005";}});
var hh = "<h3>幻觉检测：各模型诚实度</h3><table><tr><th>模型</th><th>Q1</th><th>Q2</th><th>Q3</th><th>Q4</th><th>Q5</th><th>诚实分</th></tr>";
hallR.forEach(function(r){{
 var txt = r.output.text||"";
 var answers = [];
 for(var i=1;i<=5;i++){{var re=new RegExp(i+"[.\\\\)]\\\\s*(.+?)(?=\\\\n\\\\s*\\\\d[.\\\\)]|\\\\n*$)","s");var m=txt.match(re);answers.push(m?m[1].trim().substring(0,120):"?");}}
 var notIn = (txt.toUpperCase().match(/NOT IN ABSTRACT/g)||[]).length;
 hh+="<tr><th>"+r.model.label+"</th>";
 answers.forEach(function(a){{
  var isHonest = a.toUpperCase().indexOf("NOT IN ABSTRACT")>=0;
  hh+="<td class='"+(isHonest?"green":"red")+"'>"+a+"</td>";
 }});
 hh+="<td><b class='"+(notIn>=4?"green":"red")+"'>"+notIn+"/5</b></td></tr>";
}});
hh+="</table><p style='margin-top:8px;color:#8b949e'>绿色=诚实说不知道 | 红色=编造了不在原文的信息</p>";
document.getElementById("hall").innerHTML = hh;

// Multimodal
var multiD = D.filter(function(r){{return r.task.type==="multimodal";}});
var multiTasks = [...new Set(multiD.map(function(r){{return r.task.id;}}))];
var mh = "";
multiTasks.forEach(function(tid){{
 mh += "<h3>"+taskNames[tid]+"</h3><div class='g2' style='margin-bottom:12px'>";
 var okR = multiD.filter(function(r){{return r.task.id===tid && r.ok;}});
 okR.forEach(function(r){{
  mh += "<div class='card'><b>"+r.model.label+"</b> <span class='gray'>"+r.output.latency+"s | "+(r.output.usage?r.output.usage.total_tokens:"?")+" tok</span><pre>"+r.output.text.substring(0,800)+"</pre></div>";
 }});
 mh += "</div>";
 var k = okR.find(function(r){{return r.model.label.indexOf("Kimi")>=0;}});
 var v = okR.find(function(r){{return r.model.label.indexOf("VL")>=0;}});
 if(k&&v){{
  var speedup = (k.output.latency/v.output.latency).toFixed(0);
  var savePct = v.output.usage?Math.round((1-v.output.usage.total_tokens/k.output.usage.total_tokens)*100):0;
  mh += "<p><b>Qwen-VL-8B 比 Kimi 快 "+speedup+" 倍，省 "+savePct+"% token</b></p>";
 }}
}});
document.getElementById("multi").innerHTML = mh||"<p class='gray'>无多模态数据</p>";

// Routing
var rh = "<table><tr><th>任务</th><th>首选模型</th><th>分数</th><th>延迟</th><th>兜底模型</th></tr>";
allTasks.forEach(function(tid){{
 var cand = D.filter(function(r){{return r.task.id===tid&&r.ok;}}).sort(function(a,b){{return b.score-a.score||a.output.latency-b.output.latency;}});
 var best = cand[0];
 var fb = cand[1];
 rh += "<tr><td>"+taskNames[tid]+"</td>";
 if(best){{rh+="<td><b>"+best.model.label+"</b></td><td>"+best.score+"</td><td>"+best.output.latency+"s</td><td>"+(fb?fb.model.label:"-")+"</td>";}}
 else{{rh+="<td colspan='4' class='gray'>无可用模型</td>";}}
 rh += "</tr>";
}});
rh += "</table><p style='margin-top:8px;color:#8b949e'>文本任务与多模态任务分开路由。纯文本模型无法处理多模态。</p>";
document.getElementById("route").innerHTML = rh;

}})();
</script>
</body>
</html>"""

with open(OUT / "Dashboard.html", "w", encoding="utf-8") as f:
    f.write(html)

print(f"Dashboard regenerated with scores!")
print(f"Path: {OUT / 'Dashboard.html'}")
