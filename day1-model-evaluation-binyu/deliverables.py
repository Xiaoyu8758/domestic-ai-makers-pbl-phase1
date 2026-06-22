#!/usr/bin/env python3
"""Generate teacher-required deliverable files from evaluation results."""
import json
from datetime import datetime
from pathlib import Path


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def short(text, limit: int = 220) -> str:
    clean = " ".join(str(text or "").split())
    return clean if len(clean) <= limit else clean[: limit - 1] + "..."


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [OK] {path.name}")


def _write_md(path: Path, title: str, body: str) -> None:
    path.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
    print(f"  [OK] {path.name}")


# ── model_capability_matrix.json ──

def build_matrix(results: list[dict]) -> dict:
    """Build model capability matrix from results."""
    import statistics

    tasks: dict[str, dict] = {}
    models: dict[str, dict] = {}
    for item in results:
        tkey = item["task"]["id"]
        tasks.setdefault(tkey, {
            "id": tkey,
            "title": item["task"]["title"],
            "type": item["task"]["type"],
        })
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

        # Recommendation per role
        recommendations = []
        if task_scores.get("paper_summary_001", 0) >= 4:
            recommendations.append("论文理解与创新提炼")
        if task_scores.get("paper_methods_002", 0) >= 4:
            recommendations.append("结构化信息抽取")
        if task_scores.get("paper_translate_003", 0) >= 4:
            recommendations.append("术语保真翻译")
        if task_scores.get("paper_scenario_004", 0) >= 4:
            recommendations.append("场景适配推理")
        if task_scores.get("paper_hallucination_005", 0) >= 3:
            recommendations.append("事实诚实性审查")
        if any(task_scores.get(t, 0) >= 4 for t in ["multimodal_arch_006", "multimodal_error_007"]):
            recommendations.append("多模态图表理解")
        if not recommendations:
            recommendations.append("低风险辅助生成")

        matrix.append({
            "model_label": label,
            "model_id": m["id"],
            "avg_score": round(statistics.mean(scores), 2) if scores else 0,
            "avg_latency": round(statistics.mean(lats), 2) if lats else 0,
            "avg_tokens": round(statistics.mean(toks), 1) if toks else 0,
            "task_scores": task_scores,
            "strengths": strengths,
            "risks": risks,
            "recommendation": recommendations,
        })

    leaderboards = {}
    for tkey, task in tasks.items():
        ranking = [
            {
                "model": r["model"]["label"],
                "score": r["score"],
                "latency": r["output"]["latency"],
                "sample": short(r["output"].get("text", ""), 260),
            }
            for r in results
            if r["task"]["id"] == tkey
        ]
        ranking.sort(key=lambda x: (-x["score"], x["latency"]))
        leaderboards[tkey] = {"task": task, "ranking": ranking}

    return {
        "generated_at": now(),
        "arena_name": "Day1 论文阅读理解能力评估",
        "models": [{"label": m["label"], "id": m["id"]} for _, m in sorted(models.items())],
        "tasks": list(tasks.values()),
        "matrix": matrix,
        "leaderboards": leaderboards,
        "assessment_focus": [
            "同一论文的多模型理解对比，形成可复用的工程证据。",
            "保留原始输出、评分、失败样本和选型理由。",
            "把论文阅读理解能力差异转化为 Day2 能力模块的模型路由规则。",
            "文本模型和多模态模型分开评估，避免用单一总分覆盖任务差异。",
        ],
    }


# ── day1_to_day2_brief.json ──

def build_day2_brief(matrix: dict) -> dict:
    """Build routing brief for Day2 from capability matrix."""
    role_map = {
        "content_summarizer": "paper_summary_001",
        "info_extractor": "paper_methods_002",
        "translator": "paper_translate_003",
        "scenario_analyst": "paper_scenario_004",
        "fact_checker": "paper_hallucination_005",
        "multimodal_analyst": "multimodal_arch_006",
    }

    router = {}
    for role, tkey in role_map.items():
        ranking = matrix.get("leaderboards", {}).get(tkey, {}).get("ranking", [])
        best = ranking[0] if ranking else {"model": "N/A", "score": 0}
        second = ranking[1] if len(ranking) > 1 else best
        router[role] = {
            "preferred_model": best["model"],
            "evidence_task": tkey,
            "score": best["score"],
            "fallback_model": second["model"],
            "fallback_rule": "如输出为空/不可解析/延迟过高，切换到兜底模型",
        }

    return {
        "generated_at": now(),
        "purpose": "将 Day1 论文阅读理解能力评估结果转化为 Day2 的模型路由依据。",
        "product_direction": "论文学术阅读理解：摘要提炼、方法提取、术语翻译、场景推理、幻觉检测、图表理解",
        "router": router,
        "day2_requirements": [
            "提示词库必须区分内容摘要、信息抽取、翻译、推理、事实核查、多模态理解。",
            "多模态任务必须单独记录候选模型、输入类型和 fallback。",
            "结构化输出必须可解析为 JSON，并能被 Day3 Agent Core 读取。",
            "Day2 需要交付可调用的能力模块和 handoff 合约。",
        ],
        "assessment_question": "学生能否说明为什么某个模型适合某个论文阅读任务，并能用失败样本支持 fallback 设计。",
    }


# ── model_pool_policy.json ──

def build_model_pool_policy(matrix: dict) -> dict:
    """Build model pool policy JSON."""
    return {
        "generated_at": now(),
        "provider": "SiliconFlow",
        "classroom_policy": (
            "学生从硅基流动模型池中选择候选模型进行论文阅读理解评测。"
            "参考答案中的 DeepSeek、Qwen、GLM、Kimi、Qwen-VL 为 baseline。"
        ),
        "baseline_models": [{"label": m["label"], "id": m["id"]} for m in matrix.get("models", [])],
        "selection_tracks": [
            {
                "track": "text_reading",
                "required": True,
                "min_candidates": 2,
                "covers": ["content_summarizer", "info_extractor", "translator", "scenario_analyst", "fact_checker"],
            },
            {
                "track": "multimodal_reading",
                "required": "if_available",
                "min_candidates": 1,
                "covers": ["multimodal_analyst"],
            },
        ],
        "routing_roles": [
            "content_summarizer", "info_extractor", "translator",
            "scenario_analyst", "fact_checker", "multimodal_analyst",
        ],
        "assessment_rule": "每个角色至少有一组主模型+兜底模型+失败条件。",
    }


# ── failure_casebook.md ──

def build_failure_casebook(results: list[dict]) -> str:
    """Generate failure casebook markdown from results."""
    lines = ["## 失败/风险样本", ""]
    count = 0
    for item in results:
        text = item["output"].get("text", "") if item.get("ok") else item["output"].get("text", "")
        score = item.get("score", 0)
        if score <= 2 or not item.get("ok") or len(text) < 80:
            count += 1
            title = item["task"]["title"]
            model = item["model"]["label"]
            lines.append(f"### {title} / {model} / score={score}")
            reason = "API 调用失败" if not item.get("ok") else ("回复过短" if len(text) < 80 else f"得分较低 ({score}/5)")
            lines.append(f"- 风险摘要：{reason} — {short(text, 300)}")
            lines.append("- 课堂追问：这个失败会如何影响 Day2 能力模块的稳定性？")
            lines.append("")

    if count == 0:
        lines.append("当前样本整体得分较高，课堂可让学生主动构造反例。")
        lines.append("")

    return "\n".join(lines)


# ── model_selection_playbook.md ──

def build_model_selection_playbook(matrix: dict) -> str:
    """Generate model selection playbook markdown."""
    parts = [
        "## 选型原则",
        "- 论文理解、信息抽取、翻译保真、场景推理、事实诚实性要分开评估，不能用一个总分替代工程判断。",
        "- 学生可从硅基流动模型池中任选可用模型；参考答案中的 DeepSeek、Qwen、GLM、Kimi、Qwen-VL 只是 baseline。",
        "- 多模态模型单独评估：图表理解、截图诊断属于不同任务轨道。",
        "- Day2 能力模块使用多模型路由：不同论文阅读任务调用最适合的模型。",
        "- 所有模型输出必须留下原始证据、评分和失败样本，作为 assessment 的可解释依据。",
        "",
        "## 模型速览",
    ]

    for m in matrix.get("matrix", []):
        parts.append(
            f"- **{m['model_label']}**: 均分 {m['avg_score']}, "
            f"延迟 {m['avg_latency']}s, "
            f"强项: {', '.join(m['strengths'][:3]) if m['strengths'] else '无'}"
            f"{', 风险: ' + ', '.join(m['risks'][:2]) if m['risks'] else ''}"
        )

    parts.extend([
        "",
        "## Day2 接力方式",
        "- `day1_to_day2_brief.json` 直接进入 Day2 的 `context_pack/`。",
        "- Day2 必须根据该 brief 生成 Prompt Library、JSON Schema、Eval Cases 和 Agent Handoff Contract。",
    ])

    return "\n".join(parts)


# ── student_task_cards.md ──

STUDENT_TASK_CARDS = """## 学生任务卡

1. 选一个论文阅读理解任务：摘要提炼、方法提取、术语翻译、场景推理、幻觉检测、图表理解。
2. 从硅基流动模型池里选择主模型和兜底模型；参考答案可作为 baseline。
3. 写出选择理由：引用任务、原始输出、评分、失败风险和 fallback 条件。
4. 把结果写入 `day1_to_day2_brief.json`，交给 Day2 能力模块使用。

## 交付标准

- 至少说明一个模型强项。
- 至少指出一个失败或风险场景。
- 至少说明一个多模态模型的适用边界，或说明当前不选择多模态模型的原因。
- 至少给出一个 Day2 可执行的模型路由规则。
"""


# ── SUMMARY.md ──

def build_summary(results: list[dict], matrix: dict, day2_brief: dict, paper_title: str) -> str:
    """Generate SUMMARY.md markdown."""
    parts = [
        f"# Day1 评测摘要",
        f"",
        f"**论文**: {paper_title}",
        f"**评测时间**: {now()}",
        f"**模型数**: {len(matrix['models'])} | **任务数**: {len(matrix['tasks'])} | **总调用**: {len(results)}",
        f"",
        f"## 速度排名",
        f"",
        f"| 模型 | 均分 | 平均延迟 | 平均 Token |",
        f"|---|---|---|---|",
    ]
    for m in sorted(matrix["matrix"], key=lambda x: x["avg_latency"]):
        parts.append(f"| {m['model_label']} | {m['avg_score']} | {m['avg_latency']}s | {m['avg_tokens']} |")

    parts.extend([
        "",
        "## 能力矩阵",
        "",
        "| 模型 | " + " | ".join(t["title"][:6] for t in matrix["tasks"]) + " |",
        "|---" * (len(matrix["tasks"]) + 1) + "|",
    ])
    for m in matrix["matrix"]:
        scores = []
        for t in matrix["tasks"]:
            s = m["task_scores"].get(t["id"], "-")
            if isinstance(s, (int, float)):
                emoji = {5: "5", 4: "4", 3: "3", 2: "2", 1: "1"}.get(int(s), str(s))
                scores.append(emoji)
            else:
                scores.append(str(s))
        parts.append(f"| {m['model_label']} | " + " | ".join(scores) + " |")

    parts.extend([
        "",
        "## 路由建议",
        "",
        "| 角色 | 主模型 | 兜底模型 | 证据任务 |",
        "|---|---|---|---|",
    ])
    for role, info in day2_brief.get("router", {}).items():
        parts.append(f"| {role} | {info['preferred_model']} | {info.get('fallback_model', 'N/A')} | {info['evidence_task']} |")

    return "\n".join(parts)


# ── Batch generator ──

def generate_all(
    results: list[dict],
    output_dir: Path,
    paper_title: str = "",
    skip_dashboard: bool = True,
) -> dict:
    """Generate all teacher-required deliverables.

    Args:
        results: list of evaluation result dicts
        output_dir: where to write output files
        paper_title: paper title for SUMMARY.md
        skip_dashboard: if True, skip Dashboard.html (handled separately)

    Returns:
        dict with matrix and day2_brief for downstream use
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    print("\n[Deliverables] Generating...")

    matrix = build_matrix(results)
    day2_brief = build_day2_brief(matrix)
    pool_policy = build_model_pool_policy(matrix)

    _write_json(output_dir / "model_capability_matrix.json", matrix)
    _write_json(output_dir / "day1_to_day2_brief.json", day2_brief)
    _write_json(output_dir / "model_pool_policy.json", pool_policy)

    casebook = build_failure_casebook(results)
    _write_md(output_dir / "failure_casebook.md", "Day1 失败样本手册", casebook)

    playbook = build_model_selection_playbook(matrix)
    _write_md(output_dir / "model_selection_playbook.md", "Day1 模型选型手册", playbook)

    _write_md(output_dir / "student_task_cards.md", "Day1 学生任务卡", STUDENT_TASK_CARDS)

    summary = build_summary(results, matrix, day2_brief, paper_title)
    _write_md(output_dir / "SUMMARY.md", "Day1 评测摘要", summary)

    print(f"[Deliverables] Done: 7 files written to {output_dir}")
    return {"matrix": matrix, "day2_brief": day2_brief}
