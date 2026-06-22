#!/usr/bin/env python3
"""Day1 论文速读能力评估 — 国产大模型真实API调用"""
import json, os, re, sys, time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent
RESOURCES = ROOT.parent / "resources"
OUTPUTS = ROOT / "outputs-binyu"
RESULTS_FILE = OUTPUTS / "day1_results.json"


# ── 0. 加载环境配置 ──────────────────────────────────────────

def load_env() -> dict:
    env = {}
    env_file = RESOURCES / "local_siliconflow.env"
    if not env_file.exists():
        print(f"[ERROR] Missing env file: {env_file}")
        sys.exit(1)
    with open(env_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if k:
                env[k] = v.strip().strip('"').strip("'")
    return env


ENV = load_env()
API_KEY = ENV.get("SILICONFLOW_API_KEY", "")
BASE_URL = ENV.get("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
if not API_KEY:
    print("[ERROR] SILICONFLOW_API_KEY not set in resources/local_siliconflow.env")
    sys.exit(1)

MODELS = [
    {"id": "deepseek-ai/DeepSeek-V4-Flash", "label": "DeepSeek", "vision": False},
    {"id": "Qwen/Qwen2.5-72B-Instruct", "label": "Qwen2.5-72B (Alibaba)", "vision": False},
    {"id": "zai-org/GLM-5.2", "label": "GLM-5.2 (Zhipu)", "vision": False},
    {"id": "Pro/moonshotai/Kimi-K2.6", "label": "Kimi-K2.6 (Moonshot)", "vision": True},
    {"id": "Qwen/Qwen3-VL-8B-Instruct", "label": "Qwen-VL-8B (Alibaba)", "vision": True},
]


# ── 1. 任务定义 ──────────────────────────────────────────────

# 一篇接近真实论文的 abstract（视听语音分离方向）
PAPER_ABSTRACT = """We propose Swift-Net, a lightweight audio-visual speech separation
framework operating in the time domain. Unlike previous methods that rely on complex
frequency-domain processing, Swift-Net employs a power-guided grouped SRU architecture
with three key components: a LightVid Block for efficient visual encoding, a
Frequency-Time Gated Separation (FTGS) Block for audio feature extraction, and a
Selective Audio-Visual Fusion (SAF) Block for cross-modal integration. The entire
pipeline is causal, enabling real-time streaming applications. Experiments on LRS2 and
LRS3 benchmarks show that Swift-Net achieves state-of-the-art separation performance
with 40% fewer parameters and 35% lower computational cost compared to existing
methods, while maintaining a real-time factor of 0.3 on a single GPU."""

TASKS = [
    {
        "id": "paper_summary_001",
        "title": "论文创新点提炼",
        "type": "text",
        "prompt": f"""You are reviewing a paper abstract. Answer in exactly 3 sentences:
Sentence 1 — What problem does this paper solve?
Sentence 2 — What is the key method or architecture?
Sentence 3 — What is the main result or contribution?

Abstract:
{PAPER_ABSTRACT}""",
        "scoring_rubric": "5=三句话精准且无幻觉, 3=方向对但有遗漏, 1=严重错误或编造",
    },
    {
        "id": "paper_methods_002",
        "title": "方法/算法名提取",
        "type": "text",
        "prompt": f"""Extract ALL method names, algorithm names, and model architecture
component names from the abstract below. For each, write a ONE-LINE description.

Abstract:
{PAPER_ABSTRACT}""",
        "scoring_rubric": "5=全部提取且描述准确, 3=漏1-2个, 1=漏三个以上或描述错误",
    },
    {
        "id": "paper_translate_003",
        "title": "中文翻译·术语保真",
        "type": "text",
        "prompt": f"""Translate the following paper abstract into Chinese.
CRITICAL RULES:
- Keep ALL technical terms in their original English form (method names, metrics,
  framework names, model names). Do NOT translate them.
- Only translate the surrounding explanatory/narrative text.
- Preserve the original structure and meaning.

Abstract:
{PAPER_ABSTRACT}""",
        "scoring_rubric": "5=术语全部保留英文且翻译通顺, 3=少数术语被翻但可读, 1=术语全被翻或不通顺",
    },
    {
        "id": "paper_scenario_004",
        "title": "场景适配判断",
        "type": "text",
        "prompt": f"""Based on the abstract below, answer these questions:
1. Could this method be deployed on a mobile device for real-time use? Why or why not?
   Cite specific evidence from the abstract.
2. What datasets were used? Are they publicly available?
3. Would this method work for separating speech from music (instead of video)?
   Explain your reasoning.

Abstract:
{PAPER_ABSTRACT}""",
        "scoring_rubric": "5=三个问题引用原文且推理正确, 3=两个对, 1=一个或全部错误",
    },
    {
        "id": "paper_hallucination_005",
        "title": "幻觉检测·未提及事实",
        "type": "text",
        "prompt": f"""Answer the following questions about the paper abstract below.
If the abstract does NOT contain the information needed to answer, say "NOT IN ABSTRACT"
and DO NOT GUESS.

1. What specific SRU variant does Swift-Net use?
2. How many training hours were used for the LRS2 experiments?
3. What programming language and framework was used to implement Swift-Net?
4. What optimizer and learning rate schedule were used?
5. Does Swift-Net support multilingual speech separation?

Abstract:
{PAPER_ABSTRACT}""",
        "scoring_rubric": "5=对5个问题都说NOT IN ABSTRACT, 3=编造1-2个, 1=大量编造",
    },
]

# Multimodal tasks — user provides images or uses placeholders
IMAGE_TASKS = [
    {
        "id": "multimodal_arch_006",
        "title": "架构图理解",
        "type": "multimodal",
        "prompt": "Describe this architecture diagram: (1) overall data flow, (2) each major component and its role, (3) how components connect.",
        "scoring_rubric": "5=准确描述流程和组件, 3=部分正确, 1=错误",
        "image_path": "",  # user fills in
    },
    {
        "id": "multimodal_error_007",
        "title": "终端报错诊断",
        "type": "multimodal",
        "prompt": "This is a terminal error screenshot. Identify: (1) the error type, (2) the root cause, (3) the exact fix command.",
        "scoring_rubric": "5=错误识别+原因+修复全对, 3=部分正确, 1=错误",
        "image_path": "",  # user fills in
    },
]


# ── 2. API 调用 ──────────────────────────────────────────────

def call_text_model(model_id: str, prompt: str) -> dict:
    """Call a text model via SiliconFlow chat completions."""
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 800,
        "temperature": 0.3,
    }
    t0 = time.time()
    try:
        resp = requests.post(
            f"{BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
            timeout=300,
        )
        latency = round(time.time() - t0, 2)
        if resp.status_code == 200:
            data = resp.json()
            return {
                "ok": True,
                "text": data["choices"][0]["message"]["content"],
                "latency": latency,
                "usage": data.get("usage", {}),
            }
        else:
            return {
                "ok": False,
                "text": f"HTTP {resp.status_code}: {resp.text[:400]}",
                "latency": latency,
                "usage": {},
            }
    except Exception as e:
        return {
            "ok": False,
            "text": f"Request failed: {str(e)}",
            "latency": round(time.time() - t0, 2),
            "usage": {},
        }


def call_vision_model(model_id: str, prompt: str, image_path: str) -> dict:
    """Call a vision model with an image."""
    import base64

    # Encode image
    try:
        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
        ext = os.path.splitext(image_path)[1].lower().lstrip(".")
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(ext, "image/png")
        image_url = f"data:{mime};base64,{img_b64}"
    except Exception as e:
        return {"ok": False, "text": f"Image load failed: {e}", "latency": 0, "usage": {}}

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_id,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "max_tokens": 800,
        "temperature": 0.3,
    }
    t0 = time.time()
    try:
        resp = requests.post(
            f"{BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
            timeout=300,
        )
        latency = round(time.time() - t0, 2)
        if resp.status_code == 200:
            data = resp.json()
            return {
                "ok": True,
                "text": data["choices"][0]["message"]["content"],
                "latency": latency,
                "usage": data.get("usage", {}),
            }
        else:
            return {
                "ok": False,
                "text": f"HTTP {resp.status_code}: {resp.text[:400]}",
                "latency": latency,
                "usage": {},
            }
    except Exception as e:
        return {
            "ok": False,
            "text": f"Request failed: {str(e)}",
            "latency": round(time.time() - t0, 2),
            "usage": {},
        }


# ── 3. 主流程 ────────────────────────────────────────────────

def collect_images() -> dict:
    """Check for user-provided images for multimodal tasks."""
    # Match image files to tasks in order: first .png → arch task, second → error task
    search_dirs = [
        ROOT / "outputs-binyu",
        ROOT,
    ]
    candidates = []
    for d in search_dirs:
        if d.exists():
            for f in sorted(d.glob("*.png")):
                candidates.append(str(f))
            for f in sorted(d.glob("*.jpg")):
                candidates.append(str(f))
    images = {}
    if len(candidates) >= 1:
        images[IMAGE_TASKS[0]["id"]] = candidates[0]
    if len(candidates) >= 2:
        images[IMAGE_TASKS[1]["id"]] = candidates[1]
    return images


def main():
    OUTPUTS.mkdir(parents=True, exist_ok=True)

    images = collect_images()

    print("=" * 60)
    print("Day1 论文速读能力评估 — SiliconFlow 真实调用")
    print(f"Models: {', '.join(m['label'] for m in MODELS)}")
    print(f"Text tasks: {len(TASKS)}")
    mult_tasks = [t for t in IMAGE_TASKS if t["id"] in images]
    print(f"Multimodal tasks (with images): {len(mult_tasks)}")
    if IMAGE_TASKS:
        missing = [t["title"] for t in IMAGE_TASKS if t["id"] not in images]
        if missing:
            print(f"  (skipped: {', '.join(missing)} — place images in day1-model-evaluation/)")
    print("=" * 60)

    results = []

    # ── Text Tasks ──
    for task in TASKS:
        for model in MODELS:
            label, mid = model["label"], model["id"]
            tid = task["id"]
            print(f"\n[{task['title']}] → {label} ... ", end="", flush=True)
            out = call_text_model(mid, task["prompt"])
            status = "[OK]" if out["ok"] else "[FAIL]"
            print(f"{status} ({out['latency']}s, {out['usage'].get('total_tokens', '?')} tokens)")
            results.append({
                "task": {
                    "id": task["id"],
                    "title": task["title"],
                    "type": task["type"],
                    "prompt": task["prompt"],
                    "scoring_rubric": task.get("scoring_rubric", ""),
                },
                "model": {"id": mid, "label": label},
                "score": -1,  # placeholder — user scores after review
                "ok": out["ok"],
                "output": out,
            })
            time.sleep(0.5)  # avoid rate limit

    # ── Multimodal Tasks ──
    for task in IMAGE_TASKS:
        tid = task["id"]
        if tid not in images:
            continue
        img_path = images[tid]
        # Only call vision-capable models for multimodal
        for model in MODELS:
            if not model["vision"]:
                label, mid = model["label"], model["id"]
                print(f"\n[{task['title']}] → {label} (text-only, will fail as expected) ... ", end="", flush=True)
                # Try anyway — text-only models may return error
                out = call_vision_model(mid, task["prompt"], img_path)
                status = "[OK]" if out["ok"] else "[FAIL]"
                print(f"{status}")
                results.append({
                    "task": {
                        "id": task["id"],
                        "title": task["title"],
                        "type": task["type"],
                        "prompt": task["prompt"],
                        "scoring_rubric": task.get("scoring_rubric", ""),
                    },
                    "model": {"id": mid, "label": label},
                    "score": -1,
                    "ok": out["ok"],
                    "output": out,
                })
                time.sleep(0.5)
                continue

            label, mid = model["label"], model["id"]
            print(f"\n[{task['title']}] → {label} ... ", end="", flush=True)
            out = call_vision_model(mid, task["prompt"], img_path)
            status = "[OK]" if out["ok"] else "[FAIL]"
            print(f"{status} ({out['latency']}s)")
            results.append({
                "task": {
                    "id": task["id"],
                    "title": task["title"],
                    "type": task["type"],
                    "prompt": task["prompt"],
                    "scoring_rubric": task.get("scoring_rubric", ""),
                },
                "model": {"id": mid, "label": label},
                "score": -1,
                "ok": out["ok"],
                "output": out,
            })
            time.sleep(0.5)

    # ── Save ──
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 60}")
    print(f"Done. {len(results)} results saved to {RESULTS_FILE}")
    print(f"Next: review outputs & set scores in the JSON, then run:")
    print(f"  python day1_arena_builder.py")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
