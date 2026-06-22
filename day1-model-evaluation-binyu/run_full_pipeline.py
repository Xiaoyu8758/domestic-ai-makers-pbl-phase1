#!/usr/bin/env python3
"""Day1 全自动评测流水线：调API → 自动评分 → 生成报告 → 输出Dashboard"""
import json, os, re, sys, time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent
RESOURCES = ROOT.parent / "resources"
OUT = ROOT / "outputs-binyu"
OUT.mkdir(parents=True, exist_ok=True)

# ── Load env ──
def load_env():
    env = {}
    with open(RESOURCES / "local_siliconflow.env", encoding="utf-8") as f:
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
if not API_KEY:
    print("[ERROR] SILICONFLOW_API_KEY not set")
    sys.exit(1)

# ── Models ──
MODELS = [
    {"id": "deepseek-ai/DeepSeek-V4-Flash", "label": "DeepSeek", "vision": False},
    {"id": "Qwen/Qwen2.5-72B-Instruct", "label": "Qwen2.5-72B (Alibaba)", "vision": False},
    {"id": "zai-org/GLM-5.2", "label": "GLM-5.2 (Zhipu)", "vision": False},
    {"id": "Pro/moonshotai/Kimi-K2.6", "label": "Kimi-K2.6 (Moonshot)", "vision": True},
    {"id": "Qwen/Qwen3-VL-8B-Instruct", "label": "Qwen-VL-8B (Alibaba)", "vision": True},
]

# ── Tasks ──
PAPER = """We propose Swift-Net, a lightweight audio-visual speech separation
framework operating in the time domain. Unlike previous methods that rely on complex
frequency-domain processing, Swift-Net employs a power-guided grouped SRU architecture
with three key components: a LightVid Block for efficient visual encoding, a
Frequency-Time Gated Separation (FTGS) Block for audio feature extraction, and a
Selective Audio-Visual Fusion (SAF) Block for cross-modal integration. The entire
pipeline is causal, enabling real-time streaming applications. Experiments on LRS2 and
LRS3 benchmarks show that Swift-Net achieves state-of-the-art separation performance
with 40% fewer parameters and 35% lower computational cost compared to existing
methods, while maintaining a real-time factor of 0.3 on a single GPU."""

TEXT_TASKS = [
    {"id": "paper_summary_001", "title": "论文创新点提炼", "type": "text",
     "prompt": f"You are reviewing a paper abstract. Answer in exactly 3 sentences:\nSentence 1 — What problem does this paper solve?\nSentence 2 — What is the key method or architecture?\nSentence 3 — What is the main result or contribution?\n\nAbstract:\n{PAPER}",
     "rubric": "5=三句话精准且无幻觉, 3=方向对但有遗漏, 1=严重错误或编造"},
    {"id": "paper_methods_002", "title": "方法/算法名提取", "type": "text",
     "prompt": f"Extract ALL method names, algorithm names, and model architecture component names from the abstract below. For each, write a ONE-LINE description.\n\nAbstract:\n{PAPER}",
     "rubric": "5=全部提取且描述准确, 3=漏1-2个, 1=漏三个以上或描述错误"},
    {"id": "paper_translate_003", "title": "中文翻译·术语保真", "type": "text",
     "prompt": f"Translate the following paper abstract into Chinese.\nCRITICAL RULES:\n- Keep ALL technical terms in their original English form (method names, metrics, framework names, model names). Do NOT translate them.\n- Only translate the surrounding explanatory/narrative text.\n- Preserve the original structure and meaning.\n\nAbstract:\n{PAPER}",
     "rubric": "5=术语全部保留英文且翻译通顺, 3=少数术语被翻但可读, 1=术语全被翻或不通顺"},
    {"id": "paper_scenario_004", "title": "场景适配判断", "type": "text",
     "prompt": f"Based on the abstract below, answer these questions:\n1. Could this method be deployed on a mobile device for real-time use? Why or why not? Cite specific evidence from the abstract.\n2. What datasets were used? Are they publicly available?\n3. Would this method work for separating speech from music (instead of video)? Explain your reasoning.\n\nAbstract:\n{PAPER}",
     "rubric": "5=三个问题引用原文且推理正确, 3=两个对, 1=一个或全部错误"},
    {"id": "paper_hallucination_005", "title": "幻觉检测·未提及事实", "type": "text",
     "prompt": f"Answer the following questions about the paper abstract below.\nIf the abstract does NOT contain the information needed to answer, say \"NOT IN ABSTRACT\" and DO NOT GUESS.\n\n1. What specific SRU variant does Swift-Net use?\n2. How many training hours were used for the LRS2 experiments?\n3. What programming language and framework was used to implement Swift-Net?\n4. What optimizer and learning rate schedule were used?\n5. Does Swift-Net support multilingual speech separation?\n\nAbstract:\n{PAPER}",
     "rubric": "5=全部诚实回答, 3=编造1-2个, 1=大量编造"},
]

IMG_TASKS = [
    {"id": "multimodal_arch_006", "title": "架构图理解", "type": "multimodal",
     "prompt": "Describe this architecture diagram: (1) overall data flow, (2) each major component and its role, (3) how components connect.",
     "rubric": "5=准确描述流程和组件, 3=部分正确, 1=错误"},
    {"id": "multimodal_error_007", "title": "终端报错诊断", "type": "multimodal",
     "prompt": "This is a terminal error screenshot. Identify: (1) the error type, (2) the root cause, (3) the exact fix command.",
     "rubric": "5=错误识别+原因+修复全对, 3=部分正确, 1=错误"},
]

# ── Find images ──
IMAGES = {}
for f in sorted(list(OUT.glob("*.png")) + list(OUT.glob("*.jpg"))):
    if len(IMAGES) < len(IMG_TASKS):
        IMAGES[IMG_TASKS[len(IMAGES)]["id"]] = str(f)

# ── API call helpers ──
def call_text(model_id, prompt):
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {"model": model_id, "messages": [{"role": "user", "content": prompt}], "max_tokens": 800, "temperature": 0.3}
    t0 = time.time()
    try:
        resp = requests.post(f"{BASE_URL}/chat/completions", headers=headers, json=payload, timeout=300)
        lat = round(time.time() - t0, 2)
        if resp.status_code == 200:
            d = resp.json()
            return {"ok": True, "text": d["choices"][0]["message"]["content"], "latency": lat, "usage": d.get("usage", {})}
        return {"ok": False, "text": f"HTTP {resp.status_code}: {resp.text[:400]}", "latency": lat, "usage": {}}
    except Exception as e:
        return {"ok": False, "text": f"Timeout/Error: {str(e)}", "latency": round(time.time()-t0,2), "usage": {}}

def call_vision(model_id, prompt, img_path):
    import base64
    try:
        with open(img_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        ext = os.path.splitext(img_path)[1].lower().lstrip(".")
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(ext, "image/png")
        url = f"data:{mime};base64,{b64}"
    except Exception as e:
        return {"ok": False, "text": f"Image load failed: {e}", "latency": 0, "usage": {}}
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {"model": model_id, "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": url}}, {"type": "text", "text": prompt}]}], "max_tokens": 800, "temperature": 0.3}
    t0 = time.time()
    try:
        resp = requests.post(f"{BASE_URL}/chat/completions", headers=headers, json=payload, timeout=300)
        lat = round(time.time() - t0, 2)
        if resp.status_code == 200:
            d = resp.json()
            return {"ok": True, "text": d["choices"][0]["message"]["content"], "latency": lat, "usage": d.get("usage", {})}
        return {"ok": False, "text": f"HTTP {resp.status_code}: {resp.text[:400]}", "latency": lat, "usage": {}}
    except Exception as e:
        return {"ok": False, "text": f"Timeout/Error: {str(e)}", "latency": round(time.time()-t0,2), "usage": {}}


# ═══════════════════════════════════════════════════════════════
# STEP 1: Run all API evaluations
# ═══════════════════════════════════════════════════════════════
print("=" * 60)
print("STEP 1/4: Running API evaluations...")
print(f"Models: {len(MODELS)} | Text tasks: {len(TEXT_TASKS)} | Multimodal: {len(IMG_TASKS)} (images: {len(IMAGES)})")
print("=" * 60)

results = []

for task in TEXT_TASKS:
    for model in MODELS:
        label, mid = model["label"], model["id"]
        print(f"  [{task['title']}] -> {label} ... ", end="", flush=True)
        out = call_text(mid, task["prompt"])
        status = "[OK]" if out["ok"] else "[FAIL]"
        print(f"{status} ({out['latency']}s, {out['usage'].get('total_tokens','?')}t)")
        results.append({"task": task, "model": {"id": mid, "label": label}, "score": -1, "ok": out["ok"], "output": out})
        if out["ok"]:
            time.sleep(0.3)

for task in IMG_TASKS:
    tid = task["id"]
    if tid not in IMAGES:
        print(f"  [SKIP] {task['title']} - no image found")
        continue
    for model in MODELS:
        label, mid = model["label"], model["id"]
        if not model["vision"]:
            print(f"  [{task['title']}] -> {label} (text-only, skip) ... [SKIP]")
            continue
        print(f"  [{task['title']}] -> {label} ... ", end="", flush=True)
        out = call_vision(mid, task["prompt"], IMAGES[tid])
        status = "[OK]" if out["ok"] else "[FAIL]"
        print(f"{status} ({out['latency']}s)")
        results.append({"task": task, "model": {"id": mid, "label": label}, "score": -1, "ok": out["ok"], "output": out})
        if out["ok"]:
            time.sleep(0.3)

print(f"\nTotal: {len(results)} results ({sum(1 for r in results if r['ok'])} OK, {sum(1 for r in results if not r['ok'])} FAIL)")


# ═══════════════════════════════════════════════════════════════
# STEP 2: Auto-score
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("STEP 2/4: Auto-scoring...")
print("=" * 60)

REQUIRED_METHODS = {"Swift-Net", "SRU", "LightVid", "FTGS", "SAF"}

def score_response(task_id, text, ok):
    if not ok or not text:
        return 1
    text_lower = text.lower()

    if task_id == "paper_summary_001":
        has_problem = any(w in text_lower for w in ["problem", "solves", "addresses"])
        has_method = any(w in text_lower for w in ["swift-net", "architecture", "sru"])
        has_result = any(w in text_lower for w in ["40%", "35%", "state-of-the-art", "real-time"])
        score = sum([has_problem, has_method, has_result])
        if score >= 3 and len(text) > 100: return 5
        if score >= 2: return 4
        if score >= 1: return 3
        return 2

    elif task_id == "paper_methods_002":
        found = sum(1 for m in REQUIRED_METHODS if m.lower() in text_lower)
        if found >= 5: return 5
        if found >= 4: return 4
        if found >= 3: return 3
        if found >= 2: return 2
        return 1

    elif task_id == "paper_translate_003":
        chinese = sum(1 for c in text if '一' <= c <= '鿿')
        terms_preserved = all(
            kw.lower() in text_lower
            for kw in ["swift-net", "sru", "lightvid", "ftgs", "saf", "lrs2", "lrs3", "gpu"]
        )
        if chinese > 50 and terms_preserved: return 5
        if chinese > 30 and terms_preserved: return 4
        if chinese > 20: return 3
        return 2

    elif task_id == "paper_scenario_004":
        has_q1 = any(w in text_lower for w in ["mobile", "real-time", "deploy"])
        has_q2 = any(w in text_lower for w in ["lrs2", "lrs3", "dataset", "publicly"])
        has_q3 = any(w in text_lower for w in ["music", "audio-only", "visual", "video"])
        score = sum([has_q1, has_q2, has_q3])
        if score >= 3: return 5
        if score >= 2: return 3
        return 1

    elif task_id == "paper_hallucination_005":
        not_in_abstract = text.upper().count("NOT IN ABSTRACT")
        if not_in_abstract >= 4: return 5
        if not_in_abstract >= 3: return 4
        if not_in_abstract >= 2: return 3
        return 1

    elif task_id in ("multimodal_arch_006", "multimodal_error_007"):
        if not ok: return 1
        if len(text) > 200: return 4
        if len(text) > 80: return 3
        return 2

    return 3

for r in results:
    tid = r["task"]["id"]
    txt = r["output"].get("text", "")
    ok = r["ok"]
    r["score"] = score_response(tid, txt, ok)
    label = r["model"]["label"]
    print(f"  [{r['task']['title']}] {label}: score={r['score']}")

# Save after scoring
with open(OUT / "day1_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"\nScored results saved to {OUT / 'day1_results.json'}")


# ═══════════════════════════════════════════════════════════════
# STEP 3: Generate arena reports (reuse day1_arena_builder logic)
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("STEP 3/4: Generating arena reports...")
print("=" * 60)

import statistics
from datetime import datetime

def now():
    return datetime.now().isoformat(timespec="seconds")

def short(text, limit=220):
    clean = " ".join(str(text or "").split())
    return clean if len(clean) <= limit else clean[:limit-1] + "..."

def build_matrix(results):
    tasks = {}
    models = {}
    for item in results:
        tkey = item["task"]["id"]
        tasks.setdefault(tkey, {"id": tkey, "title": item["task"]["title"], "type": item["task"]["type"]})
        label = item["model"]["label"]
        models.setdefault(label, {"label": label, "id": item["model"]["id"], "items": []})
        models[label]["items"].append(item)

    matrix = []
    for label, m in sorted(models.items()):
        items = m["items"]
        scores = [r["score"] for r in items]
        lats = [r["output"]["latency"] for r in items if r["ok"]]
        toks = [r["output"]["usage"].get("total_tokens", 0) for r in items if r["ok"]]
        task_scores = {r["task"]["id"]: r["score"] for r in items}
        strengths = [r["task"]["title"] for r in items if r["score"] >= 4]
        risks = [r["task"]["title"] for r in items if r["score"] <= 2 or not r["ok"]]
        matrix.append({
            "model_label": label, "model_id": m["id"],
            "avg_score": round(statistics.mean(scores), 2) if scores else 0,
            "avg_latency": round(statistics.mean(lats), 2) if lats else 0,
            "avg_tokens": round(statistics.mean(toks), 1) if toks else 0,
            "task_scores": task_scores, "strengths": strengths, "risks": risks,
        })

    leaderboards = {}
    for tkey, task in tasks.items():
        ranking = [{"model": r["model"]["label"], "score": r["score"], "latency": r["output"]["latency"], "sample": short(r["output"].get("text",""), 260)}
                   for r in results if r["task"]["id"] == tkey]
        ranking.sort(key=lambda x: (-x["score"], x["latency"]))
        leaderboards[tkey] = {"task": task, "ranking": ranking}

    return {"generated_at": now(), "arena_name": "Day1 国产大模型能力评估", "models": [{"label": m["label"], "id": m["id"]} for _, m in sorted(models.items())], "tasks": list(tasks.values()), "matrix": matrix, "leaderboards": leaderboards}

matrix = build_matrix(results)

# day1_to_day2_brief
role_map = {"product_planner": "paper_summary_001", "context_designer": "multimodal_arch_006", "schema_generator": "paper_methods_002", "code_assistant": "paper_scenario_004", "risk_checker": "paper_hallucination_005"}
router = {}
for role, tkey in role_map.items():
    ranking = matrix["leaderboards"].get(tkey, {}).get("ranking", [])
    best = ranking[0] if ranking else {"model": matrix["models"][0]["label"], "score": 0}
    second = ranking[1] if len(ranking) > 1 else best
    router[role] = {"preferred_model": best["model"], "evidence_task": tkey, "score": best["score"], "fallback_model": second["model"], "fallback_rule": "如输出为空/不可解析/延迟过高，切换到兜底模型"}

day2_brief = {"generated_at": now(), "purpose": "Day1 -> Day2 模型路由", "router": router}

with open(OUT / "model_capability_matrix.json", "w", encoding="utf-8") as f:
    json.dump(matrix, f, ensure_ascii=False, indent=2)
with open(OUT / "day1_to_day2_brief.json", "w", encoding="utf-8") as f:
    json.dump(day2_brief, f, ensure_ascii=False, indent=2)

# Summary markdown
md_parts = ["# Day1 评测摘要\n"]
md_parts.append("## 速度排名\n")
for m in sorted(matrix["matrix"], key=lambda x: x["avg_latency"]):
    md_parts.append(f"- **{m['model_label']}**: {m['avg_latency']}s avg, {m['avg_tokens']} tokens")
md_parts.append("\n## 能力矩阵\n")
md_parts.append("| 模型 | " + " | ".join(t["title"] for t in matrix["tasks"]) + " |")
md_parts.append("|------" + "|------" * len(matrix["tasks"]) + "|")
for m in matrix["matrix"]:
    scores = [str(m["task_scores"].get(t["id"], "-")) for t in matrix["tasks"]]
    md_parts.append(f"| {m['model_label']} | " + " | ".join(scores) + " |")
md_parts.append("\n## 路由建议\n")
for role, rule in router.items():
    md_parts.append(f"- **{role}**: {rule['preferred_model']} (fallback: {rule['fallback_model']})")

with open(OUT / "SUMMARY.md", "w", encoding="utf-8") as f:
    f.write("\n".join(md_parts))

print(f"Reports generated: matrix / brief / summary")


# ═══════════════════════════════════════════════════════════════
# STEP 4: Generate Dashboard HTML
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("STEP 4/4: Generating Dashboard...")
print("=" * 60)

# Embed results JSON into HTML
data_json = json.dumps(results, ensure_ascii=False)
matrix_json = json.dumps(matrix, ensure_ascii=False)
day2_json = json.dumps(day2_brief, ensure_ascii=False)

dashboard_html = f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>论文速读能力评测 · 国产大模型对比</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
:root{{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#c9d1d9;--green:#1b5e20;--lgreen:#4caf50;--yellow:#ff9800;--orange:#f44336;--red:#b71c1c;--gray:#666}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,sans-serif;line-height:1.55}}
header{{background:var(--card);border-bottom:1px solid var(--border);padding:28px 24px;text-align:center}}
header h1{{font-size:26px;margin-bottom:4px}} header p{{color:#8b949e;font-size:14px}}
main{{max-width:1200px;margin:0 auto;padding:20px}}
.kpi-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:20px}}
.kpi-card{{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:18px;text-align:center}}
.kpi-card .num{{font-size:36px;font-weight:700}} .kpi-card .lbl{{color:#8b949e;font-size:13px;margin-top:4px}}
section{{margin-bottom:20px}}
.section-header{{background:var(--card);border:1px solid var(--border);border-radius:8px 8px 0 0;padding:14px 18px;font-size:18px;font-weight:700;cursor:pointer;display:flex;justify-content:space-between}}
.section-body{{background:var(--card);border:1px solid var(--border);border-top:0;border-radius:0 0 8px 8px;padding:18px;overflow-x:auto}}
.section-body.collapsed{{display:none}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
td,th{{border:1px solid var(--border);padding:10px 12px;text-align:center}}
th{{background:#1c2129;font-weight:600}}
.score-5{{background:var(--green);color:#fff}} .score-4{{background:var(--lgreen);color:#fff}} .score-3{{background:var(--yellow);color:#000}} .score-2{{background:var(--orange);color:#fff}} .score-1{{background:var(--red);color:#fff}} .score-pending{{background:var(--gray);color:#aaa;font-style:italic}} .score-fail{{background:#111;color:#f44}}
.chart-wrap{{max-width:600px;margin:0 auto}} .col2{{display:grid;grid-template-columns:1fr 1fr;gap:14px}} .col3{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}
.mini-card{{background:#1c2129;border:1px solid var(--border);border-radius:6px;padding:12px;font-size:13px}}
.tag-green{{color:#4caf50}} .tag-red{{color:#f44336}} .tag-gray{{color:#8b949e}}
footer{{text-align:center;color:#8b949e;font-size:12px;padding:20px;border-top:1px solid var(--border);margin-top:20px}}
@media(max-width:768px){{.kpi-grid{{grid-template-columns:repeat(2,1fr)}} .col2,.col3{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<header>
<h1>论文速读能力评测 · 国产大模型对比</h1>
<p>基于 SiliconFlow API 真实调用 · 5 模型 × 7 任务 · <span id="total-count">-</span> 次调用 · <span id="gen-time">-</span></p>
</header>
<main>
<div class="kpi-grid" id="kpi-cards"></div>

<section>
<div class="section-header" onclick="this.nextElementSibling.classList.toggle('collapsed')">📊 评分热力矩阵 <span>▼</span></div>
<div class="section-body" id="matrix-table"></div>
</section>

<section>
<div class="section-header" onclick="this.nextElementSibling.classList.toggle('collapsed')">🎯 雷达图：文本任务能力对比 <span>▼</span></div>
<div class="section-body"><div class="chart-wrap"><canvas id="radarChart"></canvas></div></div>
</section>

<section>
<div class="section-header" onclick="this.nextElementSibling.classList.toggle('collapsed')">⚡ 性能对比 <span>▼</span></div>
<div class="section-body">
<div class="col3" id="perf-panels"></div>
<div class="col2" style="margin-top:14px">
<div class="chart-wrap"><canvas id="latencyChart"></canvas></div>
<div class="chart-wrap"><canvas id="tokenChart"></canvas></div>
</div>
</div>
</section>

<section>
<div class="section-header" onclick="this.nextElementSibling.classList.toggle('collapsed')">🔍 幻觉检测专项 <span>▼</span></div>
<div class="section-body" id="hallucination-panel"></div>
</section>

<section>
<div class="section-header" onclick="this.nextElementSibling.classList.toggle('collapsed')">🖼️ 多模态专区 <span>▼</span></div>
<div class="section-body" id="multimodal-panel"></div>
</section>

<section>
<div class="section-header" onclick="this.nextElementSibling.classList.toggle('collapsed')">🗺️ 路由建议 <span>▼</span></div>
<div class="section-body" id="routing-table"></div>
</section>
</main>
<footer>数据来源：SiliconFlow API · 评分依据：准确性/完整性/诚实性 · <span id="footer-date"></span></footer>

<script>
const DATA = {data_json};
const MATRIX = {matrix_json};
const DAY2 = {day2_json};

// Render functions
(function() {{
const d = DATA;
const M = MATRIX;

document.getElementById('total-count').textContent = d.length;
document.getElementById('gen-time').textContent = M.generated_at;
document.getElementById('footer-date').textContent = M.generated_at;

// KPI
const ok = d.filter(r=>r.ok).length;
const fail = d.filter(r=>!r.ok).length;
const failReasons = {{}};
d.filter(r=>!r.ok).forEach(r=>{{const msg=r.output.text||'';const reason=msg.includes('timeout')||msg.includes('Timeout')?'Timeout':msg.includes('VLM')?'Not a VLM':msg.includes('empty')?'Empty':'Other';failReasons[reason]=(failReasons[reason]||0)+1}});
const failSummary = Object.entries(failReasons).map(([k,v])=>k+':'+v).join(', ');
document.getElementById('kpi-cards').innerHTML = `
<div class="kpi-card"><div class="num">${{new Set(d.map(r=>r.model.id)).size}}</div><div class="lbl">模型</div></div>
<div class="kpi-card"><div class="num">${{new Set(d.map(r=>r.task.id)).size}}</div><div class="lbl">任务 (5文本+2多模态)</div></div>
<div class="kpi-card"><div class="num">${{d.length}}</div><div class="lbl">总调用</div></div>
<div class="kpi-card"><div class="num" style="color:${{fail>0?'#f44':''}}">${{fail}}</div><div class="lbl">失败 (${{failSummary}})</div></div>
`;

// Matrix
const tasks = [...new Set(d.map(r=>r.task.id))];
const taskTitles = {{}};
d.forEach(r=>{{taskTitles[r.task.id]=r.task.title;}});
const models = [...new Set(d.map(r=>r.model.label))];
const modelLats = {{}};
models.forEach(m=>{{const lats=d.filter(r=>r.model.label===m&&r.ok).map(r=>r.output.latency);modelLats[m]=lats.length?lats.reduce((a,b)=>a+b,0)/lats.length:999;}});
const sortedModels = models.sort((a,b)=>modelLats[a]-modelLats[b]);

let matrixHTML = '<table><tr><th>模型</th>'+tasks.map(t=>'<th>'+taskTitles[t]+'</th>').join('')+'<th>均分</th></tr>';
sortedModels.forEach(m=>{{
let row = '<tr><th>'+m+'</th>';
let scores = [];
tasks.forEach(t=>{{
const r = d.find(x=>x.model.label===m&&x.task.id===t);
if(!r){{row+='<td>-</td>';return;}}
if(!r.ok){{row+='<td class="score-fail">FAIL</td>';scores.push(0);return;}}
const s = r.score;
scores.push(s);
let cls = s>=5?'score-5':s>=4?'score-4':s>=3?'score-3':s>=2?'score-2':s>=1?'score-1':'score-pending';
let txt = s>=0?s:'待评';
row += '<td class="'+cls+'">'+txt+'</td>';
}});
const avg = scores.length?(scores.reduce((a,b)=>a+b,0)/scores.length).toFixed(1):'-';
row += '<td><b>'+avg+'</b></td></tr>';
matrixHTML += row;
}});
matrixHTML += '</table>';
document.getElementById('matrix-table').innerHTML = matrixHTML;

// Radar
const textTasks = tasks.filter(t=>d.find(r=>r.task.id===t)?.task?.type==='text');
const ctx = document.getElementById('radarChart').getContext('2d');
const colors = ['#4caf50','#2196f3','#ff9800','#9c27b0','#f44336'];
new Chart(ctx,{{
type:'radar',
data:{{
labels:textTasks.map(t=>taskTitles[t].substring(0,6)),
datasets:sortedModels.map((m,i)=>({{
label:m,data:textTasks.map(t=>{{const r=d.find(x=>x.model.label===m&&x.task.id===t);return r&&r.ok?r.score:0;}}),
borderColor:colors[i%5],backgroundColor:colors[i%5]+'33',pointRadius:4
}}))
}},
options:{{scales:{{r:{{beginAtZero:true,max:5,ticks:{{color:'#c9d1d9'}},grid:{{color:'#30363d'}},pointLabels:{{color:'#c9d1d9'}}}}}},plugins:{{legend:{{labels:{{color:'#c9d1d9'}}}}}}}}
}});

// Performance panels
const perfHTML = sortedModels.map(m=>{{
const lats = d.filter(r=>r.model.label===m&&r.ok).map(r=>r.output.latency);
const toks = d.filter(r=>r.model.label===m&&r.ok).map(r=>r.output.usage?.total_tokens||0);
const avgL = lats.length?(lats.reduce((a,b)=>a+b,0)/lats.length).toFixed(1):'-';
const avgT = toks.length?Math.round(toks.reduce((a,b)=>a+b,0)/toks.length):'-';
const tier = avgL<15?'⚡ 经济型':avgL<60?'⚖️ 均衡型':'🐢 重型';
return '<div class="mini-card"><b>'+m+'</b><br>延迟: '+avgL+'s<br>Token: '+avgT+'<br>'+tier+'</div>';
}}).join('');
document.getElementById('perf-panels').innerHTML = perfHTML;

// Latency bar chart
const lctx = document.getElementById('latencyChart').getContext('2d');
new Chart(lctx,{{
type:'bar',
data:{{labels:tasks.map(t=>taskTitles[t].substring(0,6)),datasets:sortedModels.map((m,i)=>({{label:m,data:tasks.map(t=>{{const r=d.find(x=>x.model.label===m&&x.task.id===t);return r&&r.ok?r.output.latency:0;}}),backgroundColor:colors[i%5]+'88'}}))}},
options:{{scales:{{y:{{title:{{display:true,text:'秒',color:'#c9d1d9'}},ticks:{{color:'#c9d1d9'}},grid:{{color:'#30363d'}}}},x:{{ticks:{{color:'#c9d1d9'}}}}}},plugins:{{legend:{{labels:{{color:'#c9d1d9'}}}}}}}}
}});

// Token bar chart
const tctx = document.getElementById('tokenChart').getContext('2d');
new Chart(tctx,{{
type:'bar',
data:{{labels:sortedModels,datasets:[{{label:'Avg Tokens',data:sortedModels.map(m=>{{const toks=d.filter(r=>r.model.label===m&&r.ok).map(r=>r.output.usage?.total_tokens||0);return toks.length?Math.round(toks.reduce((a,b)=>a+b,0)/toks.length):0;}}),backgroundColor:'#ff980088'}}]}},
options:{{scales:{{y:{{title:{{display:true,text:'tokens',color:'#c9d1d9'}},ticks:{{color:'#c9d1d9'}},grid:{{color:'#30363d'}}}},x:{{ticks:{{color:'#c9d1d9'}}}}}},plugins:{{legend:{{labels:{{color:'#c9d1d9'}}}}}}}}
}});

// Hallucination
const htask = 'paper_hallucination_005';
const hallResults = d.filter(r=>r.task.id===htask);
let hallHTML = '<h3>幻觉检测：各模型诚实度</h3><table><tr><th>模型</th><th>Q1</th><th>Q2</th><th>Q3</th><th>Q4</th><th>Q5</th><th>诚实分</th></tr>';
hallResults.forEach(r=>{{
const txt = r.output.text||'';
const answers = [];
for(let i=1;i<=5;i++){{
const re = new RegExp(i+'[\\\\.\\\\)\\\\:]\\\\s*(.+?)(?=\\\\n\\\\s*\\\\d[\\\\.\\\\)]|\\\\n\\\\s*$|$)','s');
const m = txt.match(re);
answers.push(m?m[1].trim():'?');
}}
const notIn = (txt.toUpperCase().match(/NOT IN ABSTRACT/g)||[]).length;
const honest = htask==='paper_hallucination_005'?'<span class="'+(notIn>=4?'tag-green':'tag-red')+'">'+notIn+'/5</span>':'?';
hallHTML += '<tr><th>'+r.model.label+'</th>'+answers.map(a=>{{
const isHonest = a.toUpperCase().includes('NOT IN ABSTRACT');
const isWrong = a==='?'||(!isHonest && a.length>0);
return '<td class="'+(isHonest?'tag-green':isWrong?'tag-red':'')+'">'+(a.length>80?a.substring(0,80)+'...':a)+'</td>';
}}).join('')+'<td>'+honest+'</td></tr>';
}});
hallHTML += '</table><p style="margin-top:12px;color:#8b949e">✅ 诚实 = 说 NOT IN ABSTRACT · ❌ 编造 = 给了不在原文中的答案</p>';
document.getElementById('hallucination-panel').innerHTML = hallHTML;

// Multimodal
const mtasks = d.filter(r=>r.task.type==='multimodal');
const multiTasks = [...new Set(mtasks.map(r=>r.task.id))];
let multiHTML = '';
multiTasks.forEach(tid=>{{
const title = taskTitles[tid];
const visionResults = mtasks.filter(r=>r.task.id===tid);
multiHTML += '<h3>'+title+'</h3><div class="col2" style="margin-bottom:14px">';
visionResults.filter(r=>r.ok).forEach(r=>{{
multiHTML += '<div class="mini-card"><b>'+r.model.label+'</b> <span class="tag-gray">'+r.output.latency+'s | '+((r.output.usage||{{}}).total_tokens||'?')+' tok</span><pre style="white-space:pre-wrap;font-size:12px;margin-top:8px;max-height:300px;overflow-y:auto">'+(r.output.text||'').substring(0,600)+'</pre></div>';
}});
multiHTML += '</div>';
const failures = visionResults.filter(r=>!r.ok);
if(failures.length){{
multiHTML += '<p class="tag-red">文本模型不可用: '+failures.map(r=>r.model.label).join(', ')+' (均返回 "not a VLM")</p>';
}}
// Comparison
const kimi = visionResults.find(r=>r.model.label.includes('Kimi'));
const qwenVl = visionResults.find(r=>r.model.label.includes('VL'));
if(kimi&&qwenVl&&kimi.ok&&qwenVl.ok){{
const speedup = (kimi.output.latency/qwenVl.output.latency).toFixed(0);
const tokenSave = qwenVl.output.usage?.total_tokens?Math.round((1-qwenVl.output.usage.total_tokens/kimi.output.usage.total_tokens)*100):0;
multiHTML += '<p style="margin-top:8px"><b>结论：Qwen-VL-8B 比 Kimi 快 '+speedup+' 倍，省 '+tokenSave+'% token</b></p>';
}}
}});
document.getElementById('multimodal-panel').innerHTML = multiHTML||'<p class="tag-gray">无多模态数据</p>';

// Routing
let routingHTML = '<table><tr><th>任务</th><th>首选模型</th><th>分数</th><th>延迟</th><th>兜底模型</th></tr>';
tasks.forEach(tid=>{{
const candidates = d.filter(r=>r.task.id===tid&&r.ok).sort((a,b)=>b.score-a.score||a.output.latency-b.output.latency);
const best = candidates[0];
const fallback = candidates[1];
routingHTML += '<tr><td>'+taskTitles[tid]+'</td>';
if(best){{
routingHTML += '<td><b>'+best.model.label+'</b></td><td>'+best.score+'</td><td>'+best.output.latency+'s</td><td>'+(fallback?fallback.model.label:'-')+'</td>';
}} else {{
routingHTML += '<td colspan="4" class="tag-gray">无可用模型</td>';
}}
routingHTML += '</tr>';
}});
routingHTML += '</table><p style="margin-top:12px;color:#8b949e">文本任务与多模态任务分开路由。纯文本模型在多模态任务上不可用。</p>';
document.getElementById('routing-table').innerHTML = routingHTML;

}})();
</script>
</body>
</html>'''

with open(OUT / "Dashboard.html", "w", encoding="utf-8") as f:
    f.write(dashboard_html)

print(f"Dashboard saved to {OUT / 'Dashboard.html'}")
print("\n" + "=" * 60)
print("PIPELINE COMPLETE!")
print(f"Results: {OUT / 'day1_results.json'}")
print(f"Matrix:   {OUT / 'model_capability_matrix.json'}")
print(f"Brief:    {OUT / 'day1_to_day2_brief.json'}")
print(f"Summary:  {OUT / 'SUMMARY.md'}")
print(f"Dashboard:{OUT / 'Dashboard.html'}")
print("=" * 60)
