#!/usr/bin/env python3
"""Auto paper evaluation pipeline.

Usage:
    python auto_pipeline.py --arxiv 2506.06689
    python auto_pipeline.py --arxiv 2506.06689 --models 3 --no-dashboard

Input: arXiv paper ID
Output: day1_results.json + Dashboard.html + 6 teacher deliverables
"""
import argparse
import base64
import json
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

from paper_tools import (fetch_arxiv_metadata, download_pdf, extract_figures,
                          extract_key_terms, extract_figure_regions)
from deliverables import generate_all

ROOT = Path(__file__).resolve().parent
RESOURCES = ROOT.parent / "resources"
OUT = ROOT / "outputs-binyu"
OUT.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════
# Env & Config
# ═══════════════════════════════════════════════════════════════

def load_env() -> dict:
    env = {}
    env_path = RESOURCES / "local_siliconflow.env"
    if not env_path.exists():
        print(f"[WARN] {env_path} not found, trying default API key")
        return {"SILICONFLOW_API_KEY": os.environ.get("SILICONFLOW_API_KEY", ""),
                "SILICONFLOW_BASE_URL": "https://api.siliconflow.cn/v1"}
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = load_env()
API_KEY = ENV.get("SILICONFLOW_API_KEY", "")
BASE_URL = ENV.get("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")

ALL_MODELS = [
    {"id": "deepseek-ai/DeepSeek-V4-Flash", "label": "DeepSeek", "vision": False},
    {"id": "Qwen/Qwen2.5-72B-Instruct", "label": "Qwen2.5-72B (Alibaba)", "vision": False},
    {"id": "zai-org/GLM-5.2", "label": "GLM-5.2 (Zhipu)", "vision": False},
    {"id": "Pro/moonshotai/Kimi-K2.6", "label": "Kimi-K2.6 (Moonshot)", "vision": True},
    {"id": "Qwen/Qwen3-VL-8B-Instruct", "label": "Qwen-VL-8B (Alibaba)", "vision": True},
]


# ═══════════════════════════════════════════════════════════════
# API call helpers (bypass proxy for direct connection)
# ═══════════════════════════════════════════════════════════════

def _api_post(payload: dict, timeout: int = 300) -> dict:
    """POST to SiliconFlow API with proxy bypass."""
    import urllib3
    urllib3.disable_warnings()
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    t0 = time.time()
    try:
        session = requests.Session()
        session.trust_env = False
        resp = session.post(
            f"{BASE_URL}/chat/completions",
            headers=headers, json=payload,
            timeout=timeout, verify=False,
            proxies={"http": "", "https": ""},
        )
        lat = round(time.time() - t0, 2)
        if resp.status_code == 200:
            d = resp.json()
            return {"ok": True, "text": d["choices"][0]["message"]["content"],
                    "latency": lat, "usage": d.get("usage", {})}
        return {"ok": False, "text": f"HTTP {resp.status_code}: {resp.text[:400]}",
                "latency": lat, "usage": {}}
    except Exception as e:
        return {"ok": False, "text": f"Timeout/Error: {str(e)}",
                "latency": round(time.time() - t0, 2), "usage": {}}


def call_text_model(model_id: str, prompt: str, max_tokens: int = 800) -> dict:
    payload = {"model": model_id, "messages": [{"role": "user", "content": prompt}],
               "max_tokens": max_tokens, "temperature": 0.3}
    return _api_post(payload)


def call_vision_model(model_id: str, prompt: str, img_path: str,
                      max_tokens: int = 800) -> dict:
    try:
        with open(img_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        ext = os.path.splitext(img_path)[1].lower().lstrip(".")
        mime_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                     "webp": "image/webp", "gif": "image/gif"}
        mime = mime_map.get(ext, "image/png")
        url = f"data:{mime};base64,{b64}"
    except Exception as e:
        return {"ok": False, "text": f"Image load failed: {e}", "latency": 0, "usage": {}}

    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": url}},
            {"type": "text", "text": prompt},
        ]}],
        "max_tokens": max_tokens, "temperature": 0.3,
    }
    return _api_post(payload)


# ═══════════════════════════════════════════════════════════════
# Dynamic task generation
# ═══════════════════════════════════════════════════════════════

def generate_text_tasks(paper_context: dict) -> list[dict]:
    """Generate 5 text tasks with the paper abstract embedded."""
    abstract = paper_context["abstract"]
    title = paper_context["title"]

    return [
        {
            "id": "paper_summary_001",
            "title": "论文创新点提炼",
            "type": "text",
            "prompt": (
                f"You are reviewing a paper abstract. Answer in exactly 3 sentences:\n"
                f"Sentence 1 — What problem does this paper solve?\n"
                f"Sentence 2 — What is the key method or architecture?\n"
                f"Sentence 3 — What is the main result or contribution?\n\n"
                f"Abstract:\n{abstract}"
            ),
            "scoring_rubric": "5=三句话精准且无幻觉, 3=方向对但有遗漏, 1=严重错误或编造",
        },
        {
            "id": "paper_methods_002",
            "title": "方法/算法名提取",
            "type": "text",
            "prompt": (
                f"Extract ALL method names, algorithm names, and model architecture "
                f"component names from the abstract below. For each, write a ONE-LINE "
                f"description.\n\nAbstract:\n{abstract}"
            ),
            "scoring_rubric": "5=全部提取且描述准确, 3=漏1-2个, 1=漏三个以上或描述错误",
        },
        {
            "id": "paper_translate_003",
            "title": "中文翻译·术语保真",
            "type": "text",
            "prompt": (
                f"Translate the following paper abstract into Chinese.\n"
                f"CRITICAL RULES:\n"
                f"- Keep ALL technical terms in their original English form (method names, "
                f"metrics, framework names, model names). Do NOT translate them.\n"
                f"- Only translate the surrounding explanatory/narrative text.\n"
                f"- Preserve the original structure and meaning.\n\n"
                f"Abstract:\n{abstract}"
            ),
            "scoring_rubric": "5=术语全部保留英文且翻译通顺, 3=少数术语被翻但可读, 1=术语全被翻或不通顺",
        },
        {
            "id": "paper_scenario_004",
            "title": "场景适配判断",
            "type": "text",
            "prompt": (
                f"Based on the abstract below, answer these questions:\n"
                f"1. Could this method be deployed on a mobile device for real-time use? "
                f"Why or why not? Cite specific evidence from the abstract.\n"
                f"2. What datasets were used? Are they publicly available?\n"
                f"3. Would this method work for a different domain than the one studied? "
                f"Explain your reasoning.\n\n"
                f"Abstract:\n{abstract}"
            ),
            "scoring_rubric": "5=三个问题引用原文且推理正确, 3=两个对, 1=一个或全部错误",
        },
        {
            "id": "paper_hallucination_005",
            "title": "幻觉检测·未提及事实",
            "type": "text",
            "prompt": _generate_hallucination_prompt(abstract, paper_context.get("key_terms", [])),
            "scoring_rubric": "5=全部诚实回答NOT IN ABSTRACT, 3=编造1-2个, 1=大量编造",
        },
    ]


def _generate_hallucination_prompt(abstract: str, key_terms: list[str]) -> str:
    """Generate 5 trap questions about information NOT in the abstract."""
    # Pick the first key term that looks like a method name
    main_method = ""
    for t in key_terms:
        if any(c.isupper() for c in t) and len(t) > 3 and "-" not in t.lower()[:4]:
            main_method = t.split()[0]
            break
    if not main_method and key_terms:
        main_method = key_terms[0].split()[0]
    if not main_method:
        main_method = "this method"

    q1 = f"1. What specific variant or version of {main_method} does the paper use?"
    q2 = "2. How many training hours or data points were used in the experiments?"
    q3 = "3. What programming language and deep learning framework was used for implementation?"
    q4 = "4. What optimizer, learning rate, and batch size were used for training?"
    q5 = "5. Does this method support cross-domain or multilingual applications?"

    return (
        f"Answer the following questions about the paper abstract below.\n"
        f'If the abstract does NOT contain the information needed to answer, '
        f'say "NOT IN ABSTRACT" and DO NOT GUESS.\n\n'
        f"{q1}\n{q2}\n{q3}\n{q4}\n{q5}\n\n"
        f"Abstract:\n{abstract}"
    )


def generate_multimodal_tasks(figures: list[Path]) -> list[dict]:
    """Generate multimodal tasks for extracted figures."""
    if not figures:
        return []

    tasks = []
    for i, fig_path in enumerate(figures[:8]):  # Max 8 multimodal tasks (embedded + rendered pages)
        fig_num = i + 1
        tasks.append({
            "id": f"multimodal_fig_{fig_num:03d}",
            "title": f"图表理解·图{fig_num}",
            "type": "multimodal",
            "image_path": str(fig_path),
            "prompt": (
                f"Describe this figure from the paper in detail:\n"
                f"(1) What type of visualization is this (architecture diagram, chart, "
                f"table, plot, etc.)?\n"
                f"(2) What are the key components, variables, or data shown?\n"
                f"(3) What is the main insight or conclusion conveyed by this figure?"
            ),
            "scoring_rubric": "5=准确描述图表类型和关键信息, 3=部分正确, 1=错误",
        })
    return tasks


# ═══════════════════════════════════════════════════════════════
# Adaptive scoring
# ═══════════════════════════════════════════════════════════════

def score_response(task_id: str, text: str, ok: bool,
                   key_terms=None) -> int:
    """Score a model response adaptively using extracted key terms."""
    if not ok or not text:
        return 1

    if key_terms is None:
        key_terms = []

    text_lower = text.lower()
    terms_lower = [t.lower() for t in key_terms]

    if task_id == "paper_summary_001":
        # Check 3-sentence structure and key term coverage
        sentences = [s.strip() for s in text.replace("\n", " ").split(".") if s.strip()]
        has_3_sentences = len(sentences) >= 3
        term_hits = sum(1 for t in terms_lower[:5] if t in text_lower)
        if has_3_sentences and term_hits >= 3 and len(text) > 100:
            return 5
        if term_hits >= 2 and len(text) > 80:
            return 4
        if term_hits >= 1:
            return 3
        return 2

    elif task_id == "paper_methods_002":
        # Count how many key terms are found
        search_terms = key_terms[:8] if len(key_terms) >= 8 else key_terms
        if not search_terms:
            # Fallback: check for capitalized acronyms in response
            search_terms = ["method", "model", "architecture", "framework"]
        found = sum(1 for t in search_terms if t.lower() in text_lower)
        total = max(len(search_terms), 1)
        ratio = found / total
        if ratio >= 0.8: return 5
        if ratio >= 0.6: return 4
        if ratio >= 0.4: return 3
        if ratio >= 0.2: return 2
        return 1

    elif task_id == "paper_translate_003":
        chinese_count = sum(1 for c in text if '一' <= c <= '鿿')
        # Check key term preservation
        top_terms = key_terms[:6] if key_terms else []
        preserved = sum(1 for t in top_terms if t.lower() in text_lower)
        total = max(len(top_terms), 1)
        pres_ratio = preserved / total
        if chinese_count > 50 and pres_ratio >= 0.8:
            return 5
        if chinese_count > 30 and pres_ratio >= 0.6:
            return 4
        if chinese_count > 20:
            return 3
        return 2

    elif task_id == "paper_scenario_004":
        has_q1 = any(w in text_lower for w in ["mobile", "real-time", "deploy", "device"])
        has_q2 = any(w in text_lower for w in ["dataset", "benchmark", "publicly", "available"])
        has_q3 = any(w in text_lower for w in ["domain", "different", "generalize", "applicable"])
        score = sum([has_q1, has_q2, has_q3])
        if score >= 3: return 5
        if score >= 2: return 3
        return 1

    elif task_id == "paper_hallucination_005":
        not_count = text.upper().count("NOT IN ABSTRACT")
        if not_count >= 5: return 5
        if not_count >= 3: return 3
        if not_count >= 1: return 2
        return 1

    elif task_id.startswith("multimodal_"):
        # Length + visual term presence
        visual_terms = ["figure", "diagram", "chart", "plot", "table", "shows",
                        "illustrates", "depicts", "component", "architecture",
                        "axis", "layer", "block", "module", "graph"]
        visual_hits = sum(1 for v in visual_terms if v in text_lower)
        if len(text) > 200 and visual_hits >= 3: return 5
        if len(text) > 100 and visual_hits >= 2: return 4
        if len(text) > 50: return 3
        return 2

    return 3


# ═══════════════════════════════════════════════════════════════
# Dashboard HTML builder (parameterized)
# ═══════════════════════════════════════════════════════════════

def _short(s: str, limit: int = 220) -> str:
    clean = " ".join(str(s or "").split())
    return clean if len(clean) <= limit else clean[: limit - 1] + "..."


def build_dashboard_html(results: list[dict], paper_context: dict,
                         matrix: dict, day2_brief: dict) -> str:
    """Generate Dashboard HTML with embedded data."""
    now_str = datetime.now().isoformat(timespec="seconds")
    paper_title = paper_context.get("title", "Unknown Paper")

    # Model stats
    models_map: dict[str, dict] = {}
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

    data_json = json.dumps(results, ensure_ascii=False).replace("</", "<\\/")
    models_json = json.dumps(sorted_models, ensure_ascii=False).replace("</", "<\\/")

    # Task ids
    all_task_ids = list(dict.fromkeys(r["task"]["id"] for r in results))
    text_task_ids = [t for t in all_task_ids if t.startswith("paper_")]
    multi_task_ids = [t for t in all_task_ids if t.startswith("multimodal_")]
    text_ids_json = json.dumps(text_task_ids)
    multi_ids_json = json.dumps(multi_task_ids)

    # VLM filter
    vlm_labels_json = json.dumps([
        m["label"] for m in ALL_MODELS if m["vision"]
    ])

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>论文速读能力评测 — {_short(paper_title, 60)}</title>
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
.chart-box h4{{font-size:13px;font-weight:600}}
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
<header>
  <h1>论文速读能力评测</h1>
  <p>{_short(paper_title, 120)}</p>
  <p style="margin-top:6px">SiliconFlow API | {len(sorted_models)} 个模型 × {len(all_task_ids)} 个任务 | <span id="tc">-</span> 次调用 | {now_str}</p>
</header>
<main>
<div class="kpi-row" id="kpi"></div>

<section>
<div class="sh" onclick="this.nextElementSibling.classList.toggle('hide')">评分热力图 <span style="float:right">&#9660;</span></div>
<div class="sb" id="matrix"></div>
</section>

<section>
<div class="sh" onclick="this.nextElementSibling.classList.toggle('hide')">雷达图：文本任务能力 <span style="float:right">&#9660;</span></div>
<div class="sb"><div class="chart-box"><canvas id="radar"></canvas></div></div>
</section>

<section>
<div class="sh" onclick="this.nextElementSibling.classList.toggle('hide')">性能指标 <span style="float:right">&#9660;</span></div>
<div class="sb">
<div class="g3" id="perf"></div>
<div class="g2" style="margin-top:12px">
<div class="chart-box"><h4 style="text-align:center;color:#8b949e;margin-bottom:8px">文本任务延迟 (秒)</h4><canvas id="latBar"></canvas></div>
<div class="chart-box"><h4 style="text-align:center;color:#8b949e;margin-bottom:8px">文本任务 Token</h4><canvas id="tokBar"></canvas></div>
</div>
<div class="g2" style="margin-top:12px">
<div class="chart-box"><h4 style="text-align:center;color:#8b949e;margin-bottom:8px">多模态任务延迟 (秒)</h4><canvas id="mmLatBar"></canvas></div>
<div class="chart-box"><h4 style="text-align:center;color:#8b949e;margin-bottom:8px">多模态任务 Token</h4><canvas id="mmTokBar"></canvas></div>
</div>
</div>
</section>

<section>
<div class="sh" onclick="this.nextElementSibling.classList.toggle('hide')">幻觉检测 <span style="float:right">&#9660;</span></div>
<div class="sb" id="hall"></div>
</section>

<section>
<div class="sh" onclick="this.nextElementSibling.classList.toggle('hide')">多模态区域 <span style="float:right">&#9660;</span></div>
<div class="sb" id="multi"></div>
</section>

<section>
<div class="sh" onclick="this.nextElementSibling.classList.toggle('hide')">路由建议 <span style="float:right">&#9660;</span></div>
<div class="sb" id="route"></div>
</section>
</main>
<footer>auto_pipeline.py | SiliconFlow API | 自适应评分：基于关键术语自动提取</footer>

<script type="application/json" id="eval-data">{data_json}</script>
<script type="application/json" id="model-stats">{models_json}</script>
<script>
(function() {{
  "use strict";

  var D = JSON.parse(document.getElementById("eval-data").textContent);
  var sortedModels = JSON.parse(document.getElementById("model-stats").textContent);
  var hasCharts = typeof Chart !== "undefined";

  document.getElementById("tc").textContent = D.length;

  var tasks = [...new Set(D.map(function(r){{return r.task.id;}}))];
  var taskNames = {{}}; D.forEach(function(r){{taskNames[r.task.id]=r.task.title;}});
  var models = sortedModels.map(function(m){{return m.label;}});
  var okCount = D.filter(function(r){{return r.ok;}}).length;
  var failCount = D.filter(function(r){{return !r.ok;}}).length;
  var failReasons = D.filter(function(r){{return !r.ok;}}).map(function(r){{
   var m = r.output.text||""; return m.indexOf("timeout")>=0||m.indexOf("Timeout")>=0?"超时":m.indexOf("VLM")>=0?"不支持图片":"其他";
  }});
  var frCount = {{}}; failReasons.forEach(function(r){{frCount[r]=(frCount[r]||0)+1;}});
  var frStr = Object.keys(frCount).map(function(k){{return k+":"+frCount[k];}}).join(", ");
  document.getElementById("kpi").innerHTML =
   "<div class='kpi'><div class='n'>"+models.length+"</div><div class='l'>模型数</div></div>"+
   "<div class='kpi'><div class='n'>"+tasks.length+"</div><div class='l'>任务数</div></div>"+
   "<div class='kpi'><div class='n'>"+D.length+"</div><div class='l'>调用次数 ("+okCount+" 成功)</div></div>"+
   "<div class='kpi'><div class='n"+(failCount>0?" warn":"")+"'>"+failCount+"</div><div class='l'>失败 ("+frStr+")</div></div>";

  // Matrix
  var textTasks = {text_ids_json};
  var multiTasks = {multi_ids_json};
  var allTasks = textTasks.concat(multiTasks);
  var h = "<table><tr><th>模型</th>";
  allTasks.forEach(function(t){{h+="<th title='"+taskNames[t]+"'>"+taskNames[t].substring(0,6)+"</th>";}});
  h+="<th>均分</th></tr>";
  models.forEach(function(m){{
   h+="<tr><th>"+m+"</th>";
   var scores = [];
   allTasks.forEach(function(t){{
    var r = D.find(function(x){{return x.model.label===m && x.task.id===t;}});
    if(!r){{h+="<td>-</td>";return;}}
    if(!r.ok){{h+="<td class='s1'>不支持</td>";scores.push(0);return;}}
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

  // Radar (text tasks only)
  var colors = ["#4caf50","#2196f3","#ff9800","#9c27b0","#f44336"];
  if(hasCharts && textTasks.length > 0){{
    var ctx = document.getElementById("radar").getContext("2d");
    new Chart(ctx,{{
      type:"radar",
      data:{{
        labels:textTasks.map(function(t){{return taskNames[t].substring(0,8);}}),
        datasets:models.map(function(m,i){{return{{
          label:m,
          data:textTasks.map(function(t){{var r=D.find(function(x){{return x.model.label===m&&x.task.id===t;}});return r&&r.ok?r.score:0;}}),
          borderColor:colors[i%5],backgroundColor:colors[i%5]+"22",borderWidth:2,pointRadius:4,pointBackgroundColor:colors[i%5]
        }};}})
      }},
      options:{{scales:{{r:{{beginAtZero:true,max:5,ticks:{{color:"#c9d1d9"}},grid:{{color:"#30363d"}},pointLabels:{{color:"#c9d1d9"}}}}}},plugins:{{legend:{{labels:{{color:"#c9d1d9",usePointStyle:true,pointStyleWidth:8,boxWidth:8,boxHeight:8}}}}}}}}
    }});
  }}

  // Performance cards
  document.getElementById("perf").innerHTML = sortedModels.map(function(m){{
   var tier = m.avg_latency<15?"经济型":m.avg_latency<60?"均衡型":"重量型";
   return "<div class='card'><b>"+m.label+"</b><br>延迟: "+m.avg_latency+"s | Token: "+m.avg_tokens+"<br>级别: "+tier+"</div>";
  }}).join("");

  // Text tasks latency chart
  if(hasCharts && textTasks.length > 0){{
    var lctx = document.getElementById("latBar").getContext("2d");
    new Chart(lctx,{{
      type:"bar",
      data:{{labels:textTasks.map(function(t){{return taskNames[t].substring(0,6);}}),datasets:models.map(function(m,i){{return{{label:m,data:textTasks.map(function(t){{var r=D.find(function(x){{return x.model.label===m&&x.task.id===t;}});return r&&r.ok?r.output.latency:0;}}),backgroundColor:colors[i%5]+"88"}};}})}},
      options:{{scales:{{y:{{title:{{display:true,text:"秒",color:"#c9d1d9"}},ticks:{{color:"#c9d1d9"}},grid:{{color:"#30363d"}}}},x:{{ticks:{{color:"#c9d1d9"}}}}}},plugins:{{legend:{{labels:{{color:"#c9d1d9"}}}}}}}}
    }});
  }}

  // Text tasks token chart
  if(hasCharts && textTasks.length > 0){{
    var tctx = document.getElementById("tokBar").getContext("2d");
    new Chart(tctx,{{
      type:"bar",
      data:{{labels:textTasks.map(function(t){{return taskNames[t].substring(0,6);}}),datasets:models.map(function(m,i){{return{{label:m,data:textTasks.map(function(t){{var r=D.find(function(x){{return x.model.label===m&&x.task.id===t;}});return r&&r.ok&&r.output.usage?r.output.usage.total_tokens:0;}}),backgroundColor:colors[i%5]+"88"}};}})}},
      options:{{scales:{{y:{{title:{{display:true,text:"Token",color:"#c9d1d9"}},ticks:{{color:"#c9d1d9"}},grid:{{color:"#30363d"}}}},x:{{ticks:{{color:"#c9d1d9"}}}}}},plugins:{{legend:{{labels:{{color:"#c9d1d9"}}}}}}}}
    }});
  }}

  // Multimodal latency chart (VLM models only)
  var vlmLabels = {vlm_labels_json};
  if(hasCharts && multiTasks.length > 0){{
    var vlmModels = models.filter(function(m){{return vlmLabels.indexOf(m)>=0;}});
    if(vlmModels.length > 0){{
      var mlctx = document.getElementById("mmLatBar").getContext("2d");
      new Chart(mlctx,{{
        type:"bar",
        data:{{labels:multiTasks.map(function(t){{return taskNames[t].substring(0,6);}}),datasets:vlmModels.map(function(m,i){{return{{label:m,data:multiTasks.map(function(t){{var r=D.find(function(x){{return x.model.label===m&&x.task.id===t;}});return r&&r.ok?r.output.latency:0;}}),backgroundColor:["#9c27b0","#ff9800"][i%2]+"88"}};}})}},
        options:{{scales:{{y:{{title:{{display:true,text:"秒",color:"#c9d1d9"}},ticks:{{color:"#c9d1d9"}},grid:{{color:"#30363d"}}}},x:{{ticks:{{color:"#c9d1d9"}}}}}},plugins:{{legend:{{labels:{{color:"#c9d1d9"}}}}}}}}
      }});
    }}
  }}

  // Multimodal token chart
  if(hasCharts && multiTasks.length > 0){{
    var vlmModels2 = models.filter(function(m){{return vlmLabels.indexOf(m)>=0;}});
    if(vlmModels2.length > 0){{
      var mtctx = document.getElementById("mmTokBar").getContext("2d");
      new Chart(mtctx,{{
        type:"bar",
        data:{{labels:multiTasks.map(function(t){{return taskNames[t].substring(0,6);}}),datasets:vlmModels2.map(function(m,i){{return{{label:m,data:multiTasks.map(function(t){{var r=D.find(function(x){{return x.model.label===m&&x.task.id===t;}});return r&&r.ok&&r.output.usage?r.output.usage.total_tokens:0;}}),backgroundColor:["#9c27b0","#ff9800"][i%2]+"88"}};}})}},
        options:{{scales:{{y:{{title:{{display:true,text:"Token",color:"#c9d1d9"}},ticks:{{color:"#c9d1d9"}},grid:{{color:"#30363d"}}}},x:{{ticks:{{color:"#c9d1d9"}}}}}},plugins:{{legend:{{labels:{{color:"#c9d1d9"}}}}}}}}
      }});
    }}
  }}

  // Hallucination
  var hallR = D.filter(function(r){{return r.task.id==="paper_hallucination_005";}});
  if(hallR.length > 0){{
    // Parse 5 trap questions from the first result's prompt
    var hallPrompt = hallR[0].task.prompt||"";
    var hallQs = [];
    var qm;
    var qre = /(\\d+)\\.\\s*(.+?)(?=\\n\\d+\\.\\s|\\n\\nAbstract)/gs;
    while((qm = qre.exec(hallPrompt)) !== null){{
      if(hallQs.length < 5) hallQs.push(qm[2].trim());
    }}
    // Short labels for column headers
    var qLabels = ["版本/变体","训练规模","框架/语言","优化器参数","跨领域"];
    var hh = "<h3>幻觉检测：模型诚实度</h3>";
    hh += "<p style='font-size:12px;color:#8b949e;margin-bottom:8px'>以下 5 个问题的正确答案都是「不在摘要中」，模型若编造即为幻觉：</p>";
    hh += "<div style='font-size:12px;color:#8b949e;margin-bottom:12px;padding:8px;background:#1c2129;border-radius:4px'>";
    hallQs.forEach(function(q,i){{ hh += "<b>Q"+(i+1)+"</b>: "+q+"<br>"; }});
    hh += "</div>";
    hh += "<table><tr><th>模型</th>";
    qLabels.forEach(function(l,i){{ hh += "<th title=" + JSON.stringify(hallQs[i]) + ">"+l+"</th>"; }});
    hh += "<th>诚实度</th></tr>";
    hallR.forEach(function(r){{
      var txt = r.output.text||"";
      var answers = [];
      for(var i=1;i<=5;i++){{var re=new RegExp(i+"[.\\\\)]\\\\s*(.+?)(?=\\\\n\\\\s*\\\\d[.\\\\)]|\\\\n*$)","s");var m=txt.match(re);answers.push(m?m[1].trim().substring(0,60):"?");}}
      var notIn = (txt.toUpperCase().match(/NOT IN ABSTRACT/g)||[]).length;
      hh+="<tr><th>"+r.model.label+"</th>";
      answers.forEach(function(a){{
        var isHonest = a.toUpperCase().indexOf("NOT IN ABSTRACT")>=0;
        hh+="<td class='"+(isHonest?"green":"red")+"' title=" + JSON.stringify(a) + ">"+(isHonest?"诚实":"编造")+"</td>";
      }});
      hh+="<td><b class='"+(notIn>=4?"green":"red")+"'>"+notIn+"/5</b></td></tr>";
    }});
    hh+="</table><p style='margin-top:8px;color:#8b949e'>绿色 = 诚实回答 | 红色 = 编造了不存在的答案 — 鼠标悬停查看原文</p>";
    document.getElementById("hall").innerHTML = hh;
  }}

  // Multimodal
  var multiD = D.filter(function(r){{return r.task.type==="multimodal";}});
  var multiTaskIds = [...new Set(multiD.map(function(r){{return r.task.id;}}))];
  var mh = "";
  multiTaskIds.forEach(function(tid){{
    mh += "<h3>"+taskNames[tid]+"</h3><div class='g2' style='margin-bottom:12px'>";
    var okR = multiD.filter(function(r){{return r.task.id===tid && r.ok;}});
    okR.forEach(function(r){{
      mh += "<div class='card'><b>"+r.model.label+"</b> <span class='gray'>"+r.output.latency+"s | "+(r.output.usage?r.output.usage.total_tokens:"?")+" tok</span><pre>"+r.output.text.substring(0,800)+"</pre></div>";
    }});
    mh += "</div>";
  }});
  document.getElementById("multi").innerHTML = mh||"<p class='gray'>无多模态数据</p>";

  // Routing
  var rh = "<table><tr><th>任务</th><th>最佳模型</th><th>分数</th><th>延迟</th><th>兜底模型</th></tr>";
  allTasks.forEach(function(tid){{
    var cand = D.filter(function(r){{return r.task.id===tid&&r.ok;}}).sort(function(a,b){{return b.score-a.score||a.output.latency-b.output.latency;}});
    var best = cand[0];
    var fb = cand[1];
    rh += "<tr><td>"+taskNames[tid]+"</td>";
    if(best){{rh+="<td><b>"+best.model.label+"</b></td><td>"+best.score+"</td><td>"+best.output.latency+"s</td><td>"+(fb?fb.model.label:"-")+"</td>";}}
    else{{rh+="<td colspan='4' class='gray'>无可用模型</td>";}}
    rh += "</tr>";
  }});
  rh += "</table><p style='margin-top:8px;color:#8b949e'>文本模型无法处理多模态任务，VLM 模型处理图片。</p>";
  document.getElementById("route").innerHTML = rh;

}})();
</script>
</body>
</html>"""
    return html


# ═══════════════════════════════════════════════════════════════
# Main pipeline
# ═══════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Auto paper evaluation pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python auto_pipeline.py --arxiv 2506.06689
  python auto_pipeline.py --arxiv 2506.06689 --models 3 --no-dashboard
  python auto_pipeline.py --arxiv 2506.06689 --skip-fetch  # use cached paper.pdf
        """,
    )
    parser.add_argument("--arxiv", required=True, help="arXiv paper ID (e.g. 2506.06689)")
    parser.add_argument("--models", type=int, default=5,
                       help="Number of models to use (1-5, default: 5)")
    parser.add_argument("--no-dashboard", action="store_true",
                       help="Skip Dashboard.html generation")
    parser.add_argument("--skip-fetch", action="store_true",
                       help="Skip arXiv fetch, use cached paper.pdf")
    parser.add_argument("--output-dir", type=str, default=str(OUT),
                       help="Output directory")
    args = parser.parse_args()

    if not API_KEY:
        print("[ERROR] SILICONFLOW_API_KEY not set in resources/local_siliconflow.env")
        sys.exit(1)

    models = ALL_MODELS[: args.models]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Fetch paper ──
    print("=" * 60)
    print("STEP 1/6: Fetching paper metadata...")
    print("=" * 60)

    if args.skip_fetch:
        # Read abstract from cached results
        prev = output_dir / "day1_results.json"
        if prev.exists():
            with open(prev, encoding="utf-8") as f:
                old = json.load(f)
            abstract = old[0]["task"]["prompt"].split("Abstract:\n")[-1].strip() if old else ""
            title = old[0]["task"].get("paper_title", "Unknown") if old else "Unknown"
            key_terms = extract_key_terms(abstract) if abstract else []
            paper_context = {"arxiv_id": args.arxiv, "title": title, "abstract": abstract,
                           "authors": [], "pdf_url": "", "key_terms": key_terms}
        else:
            print("[ERROR] --skip-fetch requires existing day1_results.json")
            sys.exit(1)
    else:
        paper_context = fetch_arxiv_metadata(args.arxiv)
        paper_context["key_terms"] = extract_key_terms(paper_context["abstract"])

    # ── Step 2: Download PDF & extract figures ──
    figures: list[Path] = []
    if paper_context.get("pdf_url") and not args.skip_fetch:
        print("\n" + "=" * 60)
        print("STEP 2/6: Downloading PDF & extracting figures...")
        print("=" * 60)
        pdf_path = download_pdf(paper_context["pdf_url"], output_dir)
        # Extract architecture diagrams by locating figure captions + cropping
        figures = extract_figure_regions(pdf_path, output_dir / "figures")
    elif args.skip_fetch:
        # Look for cached figures (dedup — figure_*.png would match figure_*_arch.png)
        fig_dir = output_dir / "figures"
        if fig_dir.exists():
            figures = sorted(set(
                list(fig_dir.glob("figure_*_arch.png")) +
                list(fig_dir.glob("figure_*.png")) +
                list(fig_dir.glob("figure_*.jpg")) +
                list(fig_dir.glob("figure_*.jpeg"))
            ))
        # Also check root for images
        if not figures:
            figures = sorted(set(list(output_dir.glob("*.png")) + list(output_dir.glob("*.jpg"))))
        if figures:
            print(f"[FIGURES] Found {len(figures)} cached figures (embedded + page renders)")
    else:
        print("[PDF] No PDF URL available, skipping figure extraction")

    # ── Step 3: Generate tasks ──
    print("\n" + "=" * 60)
    print("STEP 3/6: Generating tasks...")
    print("=" * 60)

    text_tasks = generate_text_tasks(paper_context)
    multimodal_tasks = generate_multimodal_tasks(figures)

    all_tasks = text_tasks + multimodal_tasks
    print(f"  Text tasks: {len(text_tasks)}")
    print(f"  Multimodal tasks: {len(multimodal_tasks)} ({len(figures)} figures)")
    print(f"  Models: {len(models)}")

    # ── Step 4: Run evaluation ──
    print("\n" + "=" * 60)
    print("STEP 4/6: Running API evaluations...")
    print("=" * 60)

    results: list[dict] = []
    total = len(all_tasks) * len(models)
    count = 0

    for task in all_tasks:
        tid = task["id"]
        ttype = task["type"]
        print(f"\n[{task['title']}] ({ttype})")

        for model in models:
            count += 1
            label = model["label"]
            mid = model["id"]

            if ttype == "text":
                out = call_text_model(mid, task["prompt"])
            elif ttype == "multimodal" and model["vision"]:
                img = task.get("image_path", "")
                if not img and figures:
                    img = str(figures[0])
                out = call_vision_model(mid, task["prompt"], img) if img else {
                    "ok": False, "text": "No image available", "latency": 0, "usage": {}}
            else:
                out = {"ok": False, "text": "Not a VLM", "latency": 0, "usage": {}}

            status = "OK" if out["ok"] else "FAIL"
            lat = out.get("latency", 0)
            print(f"  [{count}/{total}] {label}: {status} ({lat}s)")

            results.append({
                "task": {k: v for k, v in task.items() if k != "image_path"},
                "model": {"id": mid, "label": label},
                "score": -1,
                "ok": out["ok"],
                "output": out,
            })

            if out["ok"]:
                time.sleep(0.3)

    print(f"\nTotal: {len(results)} results "
          f"({sum(1 for r in results if r['ok'])} OK, "
          f"{sum(1 for r in results if not r['ok'])} FAIL)")

    # ── Step 5: Score ──
    print("\n" + "=" * 60)
    print("STEP 5/6: Scoring...")
    print("=" * 60)

    key_terms = paper_context.get("key_terms", [])
    for r in results:
        tid = r["task"]["id"]
        txt = r["output"].get("text", "")
        ok = r["ok"]
        r["score"] = score_response(tid, txt, ok, key_terms)
        print(f"  [{r['task']['title']}] {r['model']['label']}: score={r['score']}")

    # Save intermediate
    with open(output_dir / "day1_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to {output_dir / 'day1_results.json'}")

    # ── Step 6: Generate deliverables ──
    print("\n" + "=" * 60)
    print("STEP 6/6: Generating deliverables...")
    print("=" * 60)

    deliv = generate_all(results, output_dir, paper_context.get("title", ""), skip_dashboard=True)

    # Dashboard
    if not args.no_dashboard:
        html = build_dashboard_html(results, paper_context,
                                    deliv["matrix"], deliv["day2_brief"])
        dash_path = output_dir / "Dashboard.html"
        dash_path.write_text(html, encoding="utf-8")
        print(f"  [OK] Dashboard.html ({len(html)} bytes)")

    # ── Summary ──
    print("\n" + "=" * 60)
    print("Pipeline complete!")
    print(f"  Paper: {paper_context.get('title', 'Unknown')[:80]}")
    print(f"  Models: {len(models)} | Tasks: {len(all_tasks)} | Calls: {len(results)}")
    print(f"  Dashboard: {output_dir / 'Dashboard.html'}")
    print(f"  Outputs: {len(list(output_dir.glob('*')))} files in {output_dir}")
    for f in sorted(output_dir.glob("*")):
        if f.is_file() and f.suffix in (".json", ".html", ".md"):
            print(f"    - {f.name}")

    # Avg latency ranking
    lats = {}
    for r in results:
        if r["ok"]:
            m = r["model"]["label"]
            lats[m] = lats.get(m, []) + [r["output"]["latency"]]
    print("\n  Latency ranking:")
    for m, vals in sorted(lats.items(), key=lambda x: sum(x[1]) / len(x[1])):
        print(f"    {m}: avg {sum(vals)/len(vals):.1f}s")


if __name__ == "__main__":
    main()
