import json
import re
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs"
CONTENT_ROOT = ROOT.parent
DAY1_BRIEF = CONTENT_ROOT / "day1-model-evaluation-binyu" / "outputs-binyu" / "day1_to_day2_brief.json"
DAY3_SUMMARY = CONTENT_ROOT / "day3-desktop-agent-binyu" / "outputs" / "agent_workspace" / "summaries" / "course_summary.md"


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_text(path: Path, limit: int = 5000) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")[:limit]


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def tokenize(text: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}", text.lower())


def product_spec() -> Dict[str, Any]:
    return {
        "product_name": "PaperMind",
        "one_liner": "基于大模型的论文学术阅读理解助手，支持摘要提炼、方法提取、术语翻译、场景推理和论文图表理解。",
        "target_users": "需要高效阅读和理解英文学术论文的研究生、科研人员和本科高年级学生。",
        "day2_positioning": "AI Learning Capability Module：把提示词工程、上下文工程、结构化输出、多模态上下文抽取和 AI Coding 封装成可被 Day3 Agent 调用的论文阅读能力模块。",
        "core_jobs": [
            "从论文全文生成结构化复习卡（摘要、方法、关键发现）。",
            "对学生阅读理解答案进行结构化评分与查漏。",
            "把论文图表、架构图、截图描述整理成结构化上下文。",
            "把理解薄弱点和术语盲区整理成 Day3 Agent 可写入的学习状态。",
            "为 Day4 设备入口生成短回复（论文快问快答）。",
        ],
        "pain_points": [
            "英文学术论文阅读门槛高，术语和长句理解耗时。",
            "论文图表与正文分离，跨模态理解困难。",
            "缺乏针对论文理解的结构化自测工具，读后即忘。",
        ],
        "mvp_features": [
            {
                "name": "Review Card Generator",
                "user_value": "把论文内容转成可自测的问题、答案、提示和主题标签。",
                "engine_function": "generate_review_cards",
                "output_schema": "schemas/review_card.schema.json",
            },
            {
                "name": "Answer Grader",
                "user_value": "阅读理解回答后给出分数、缺漏点和下一道追问。",
                "engine_function": "grade_answer",
                "output_schema": "schemas/answer_grading.schema.json",
            },
            {
                "name": "Agent Handoff",
                "user_value": "Day3 Agent 能读取 Day2 能力模块的提示词、上下文和输出格式。",
                "engine_function": "build_agent_handoff",
                "output_schema": "schemas/agent_handoff.schema.json",
            },
            {
                "name": "Multimodal Context Extractor",
                "user_value": "把论文图表、架构图、截图描述转成 Agent 可使用的结构化上下文。",
                "engine_function": "extract_multimodal_context",
                "output_schema": "schemas/multimodal_observation.schema.json",
            },
        ],
        "model_requirements": {
            "source": "Day1 论文阅读理解能力评估与路由包",
            "routing_file": "context_pack/day1_model_brief.json",
            "rule": "从硅基流动模型池按任务选择模型；文本任务和多模态任务分开路由，输出失败时切换兜底模型。",
        },
        "hardware_touchpoint": "Day2 定义论文阅读交互内容、结构化输出和多模态上下文格式；真实设备网关放到 Day4。",
        "success_metrics": [
            "复习卡 JSON 100% 可解析。",
            "阅读理解评分输出包含 score、missing_points、next_prompt。",
            "多模态上下文输出包含 input_type、observations、uncertainties、agent_context。",
            "Day3 Agent 能读取 agent_handoff/day2_agent_contract.json。",
        ],
    }


def prompt_library(day1_brief: Dict[str, Any]) -> Dict[str, Any]:
    router = day1_brief.get("router", {})
    return {
        "generated_at": now(),
        "router_source": "Day1 模型能力评估与路由包",
        "model_policy": "模型来自硅基流动模型池；默认值只是无 Day1 路由时的占位，不限制学生选择。",
        "prompts": [
            {
                "id": "system_pocket_review_coach",
                "type": "system",
                "preferred_model": router.get("fact_checker", {}).get("preferred_model", "student-selected-fact-model"),
                "template": "你是 PaperMind，一个专精论文阅读理解的 AI 能力模块。你的职责是帮助学生高效理解英文学术论文。规则：(1) 输出必须是可解析的中文 JSON；(2) 不编造论文中没有的内容；(3) 不确定时标注 uncertainty。",
                "teaches": "系统提示词：定义领域角色（论文阅读）、核心规则（JSON 输出、不编造、标注不确定性）。",
            },
            {
                "id": "generate_review_cards",
                "type": "task",
                "preferred_model": router.get("content_summarizer", {}).get("preferred_model", "student-selected-summary-model"),
                "template": "根据论文上下文生成 3 张复习卡。每张卡覆盖一个论文阅读维度（贡献识别/图表理解/自检方法），字段必须包含 question, answer, hint, tags, source。",
                "teaches": "结构化输出：把论文阅读方法论转成机器可消费的复习卡 JSON。",
            },
            {
                "id": "grade_answer",
                "type": "task",
                "preferred_model": router.get("fact_checker", {}).get("preferred_model", "student-selected-fact-model"),
                "template": "对学生论文阅读理解答案评分。对照期望关键词检查：(1) 是否覆盖了核心概念；(2) 是否有具体细节而非泛泛而谈；(3) 逻辑是否自洽。输出 score, verdict, missing_points, next_prompt, confidence。",
                "teaches": "Evaluation：论文阅读理解评分需检查概念覆盖度、细节具体性、逻辑自洽性三个维度。",
            },
            {
                "id": "extract_multimodal_context",
                "type": "task",
                "preferred_model": router.get("multimodal_analyst", router.get("content_summarizer", {})).get("preferred_model", "student-selected-multimodal-model"),
                "template": "从论文图表（架构图/曲线图/表格/公式截图）的描述中抽取结构化上下文。根据图表类型分别提取：架构图→模块名+数据流向；曲线图→横纵轴含义+趋势；表格→行列含义+关键数值。输出 input_type, observations, text_fragments, uncertainties, agent_context。",
                "teaches": "多模态上下文工程：论文图表不是装饰，不同图表类型需要不同的抽取策略。",
            },
            {
                "id": "repair_json",
                "type": "repair",
                "preferred_model": router.get("info_extractor", {}).get("preferred_model", "student-selected-struct-model"),
                "template": "修复不可解析JSON，只输出修复后的JSON，不解释。",
                "teaches": "容错：能力模块必须处理模型格式漂移。",
            },
            {
                "id": "agent_handoff",
                "type": "handoff",
                "preferred_model": router.get("scenario_analyst", {}).get("preferred_model", "student-selected-reasoning-model"),
                "template": "把产品能力描述成Day3 Agent可调用的动作、输入、输出和文件路径。",
                "teaches": "AI Coding：把提示词资产变成工程接口。",
            },
        ],
    }


def schemas() -> Dict[str, Dict[str, Any]]:
    return {
        "review_card.schema.json": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["question", "answer", "hint", "tags", "source"],
                "properties": {
                    "question": {"type": "string"},
                    "answer": {"type": "string"},
                    "hint": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "source": {"type": "string"},
                },
            },
        },
        "answer_grading.schema.json": {
            "type": "object",
            "required": ["score", "verdict", "missing_points", "next_prompt", "confidence"],
            "properties": {
                "score": {"type": "integer", "minimum": 0, "maximum": 100},
                "verdict": {"type": "string"},
                "missing_points": {"type": "array", "items": {"type": "string"}},
                "next_prompt": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
        },
        "multimodal_observation.schema.json": {
            "type": "object",
            "required": ["input_type", "observations", "text_fragments", "uncertainties", "agent_context"],
            "properties": {
                "input_type": {"type": "string"},
                "observations": {"type": "array", "items": {"type": "string"}},
                "text_fragments": {"type": "array", "items": {"type": "string"}},
                "uncertainties": {"type": "array", "items": {"type": "string"}},
                "agent_context": {"type": "string"},
            },
        },
        "agent_handoff.schema.json": {
            "type": "object",
            "required": ["engine_name", "actions", "files", "day3_contract"],
            "properties": {
                "engine_name": {"type": "string"},
                "actions": {"type": "array"},
                "files": {"type": "object"},
                "day3_contract": {"type": "object"},
            },
        },
    }


def generate_review_cards(course_context: str) -> List[Dict[str, Any]]:
    terms = [term for term in tokenize(course_context) if len(term) >= 2]
    unique_terms = []
    for term in terms:
        if term not in unique_terms and term not in {"day3", "day4", "agent", "core"}:
            unique_terms.append(term)
    focus = unique_terms[:6] or ["摘要提炼", "方法提取", "图表理解", "幻觉检测", "场景推理", "术语翻译"]
    return [
        {
            "question": "阅读论文时，如何快速判断这篇论文的核心贡献？",
            "answer": "三步法：(1) 读 Abstract 最后一句，找 claimed contribution；(2) 看 Introduction 末尾的 contributions 列表；(3) 对照 Conclusion 验证是否兑现。三个信号一致 = 论文自洽。",
            "hint": "Abstract 末句 → Introduction 贡献列表 → Conclusion 验证。",
            "tags": ["论文阅读方法", "贡献识别", focus[0]],
            "source": "PaperMind 论文阅读能力模块",
        },
        {
            "question": "论文中的架构图应该怎么看？从哪几个维度理解？",
            "answer": "四个维度：(1) 数据流向 — 输入从哪里来、经过哪些模块、输出到哪里；(2) 模块职责 — 每个 block 解决什么问题；(3) 连接关系 — 箭头表示什么（特征传递 / 梯度回传 / 控制信号）；(4) 创新点 — 哪些模块是作者新提出的、哪些是复用的。",
            "hint": "数据流 → 模块职责 → 连接关系 → 创新点定位。",
            "tags": ["图表理解", "架构图", "多模态上下文", focus[1] if len(focus) > 1 else "图表理解"],
            "source": "PaperMind 论文阅读能力模块",
        },
        {
            "question": "怎么验证自己真的读懂了一篇论文，而不是'好像懂了'？",
            "answer": "三个自检问题：(1) 能用自己的话讲清楚方法核心思路吗？(2) 能指出方法的两个局限或假设前提吗？(3) 能想到这个方法在另一个领域的应用场景吗？三个都能回答 = 真懂；只能回答第一个 = 表面理解。",
            "hint": "自述方法 → 指出现局限 → 跨界联想。",
            "tags": ["论文阅读方法", "理解验证", "自测"],
            "source": "PaperMind 论文阅读能力模块",
        },
    ]


def extract_multimodal_context(input_type: str, description: str) -> Dict[str, Any]:
    observations = []
    if "架构图" in description or "architecture" in description.lower():
        observations.append("输入包含模型/系统架构图，需要抽取模块名称、数据流向和层级关系。")
    if "图表" in description or "figure" in description.lower():
        observations.append("输入包含论文图表，需要抽取坐标轴含义、数据趋势和关键数值区间。")
    if "截图" in description or "screen" in description.lower():
        observations.append("输入包含界面或页面截图，需要保留标题、菜单结构和状态信息。")
    if "公式" in description or "equation" in description.lower():
        observations.append("输入包含数学公式，需要记录变量定义和推导上下文。")
    if not observations:
        observations.append("输入需要先识别可见文本、主体对象和与学习任务相关的证据。")
    fragments = re.findall(r"[\u4e00-\u9fffA-Za-z0-9_:/.-]{2,}", description)[:8]
    return {
        "input_type": input_type,
        "observations": observations,
        "text_fragments": fragments,
        "uncertainties": ["没有真实图像像素时，只能基于文字描述抽取上下文。"],
        "agent_context": "；".join(observations) + " 可交给 Day3 Agent 作为检索与写文件的上下文。",
    }


def grade_answer(answer: str, expected_keywords: List[str]) -> Dict[str, Any]:
    answer_terms = set(tokenize(answer))
    expected = set(expected_keywords)
    hit = sorted(answer_terms & expected)
    score = round((len(hit) / max(1, len(expected))) * 100)
    missing = sorted(expected - answer_terms)
    return {
        "score": score,
        "verdict": "通过" if score >= 70 else "需要补强",
        "missing_points": missing,
        "next_prompt": "请补充说明论文阅读的 Day2 输出如何被 Day3 Agent 读取。" if missing else "请举一个论文快问快答的例子。",
        "confidence": 0.82 if expected else 0.5,
    }


def build_agent_handoff(spec: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "engine_name": "PaperMindCapabilityModule",
        "product_name": spec["product_name"],
        "actions": [
            {
                "name": "generate_review_cards",
                "input": "course_context: markdown/text",
                "output": "review_card[]",
                "writes": "cards/review_cards.json",
            },
            {
                "name": "grade_answer",
                "input": "question + expected_keywords + student_answer",
                "output": "answer_grading",
                "writes": "evidence/grading_result.json",
            },
            {
                "name": "extract_multimodal_context",
                "input": "input_type + image_or_screenshot_description",
                "output": "multimodal_observation",
                "writes": "knowledge/multimodal_observation.json",
            },
            {
                "name": "prepare_device_reply",
                "input": "intent + latest_agent_state",
                "output": "short_text",
                "writes": "latest_device_reply.txt",
            },
        ],
        "files": {
            "prompt_library": "prompt_library.json",
            "review_card_schema": "schemas/review_card.schema.json",
            "answer_grading_schema": "schemas/answer_grading.schema.json",
            "multimodal_observation_schema": "schemas/multimodal_observation.schema.json",
            "eval_cases": "eval_cases.json",
            "engine_report": "engine_run_report.json",
        },
        "day3_contract": {
            "read_before_run": [
                "outputs/agent_handoff/day2_agent_contract.json",
                "outputs/prompt_library.json",
                "outputs/context_pack/course_seed.md",
                "outputs/eval_cases.json",
            ],
            "use_in_agent": [
                "把Day2的schemas作为写文件格式约束。",
                "把Day2的prompt_library作为LLM任务模板。",
                "把Day2的eval_cases作为Agent输出质量检查。",
                "把多模态上下文抽取结果作为RAG检索和文件整理的补充输入。",
            ],
            "do_not_do_in_day2": [
                "不操作真实桌面文件。",
                "不配置ESP-Claw或微信。",
                "不暴露/v1/chat/completions。",
            ],
        },
    }


def eval_cases(cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "id": "eval_review_card_schema",
            "input": "输入：一篇关于语音分离的深度学习论文。期望输出 3 张复习卡，覆盖核心贡献识别、架构图阅读方法、理解自检。",
            "expected": "每张复习卡包含 question, answer, hint, tags, source 五个字段，内容围绕论文阅读方法论。",
            "actual": cards,
            "pass": all(
                all(k in card for k in ["question", "answer", "hint", "tags", "source"])
                for card in cards
            ),
            "pass_msg": "schema 完整，3 张卡片字段齐全",
            "fail_msg": "部分卡片缺少必填字段",
        },
        {
            "id": "eval_grading_hit_all_keywords",
            "input": "问：怎样才算读懂了一篇论文？学生回答：能用自己的话讲清楚方法思路，能指出两个局限，能想到跨界应用。",
            "expected_keywords": ["方法思路", "局限", "跨界", "应用"],
            "actual": grade_answer(
                "能用自己的话讲清楚方法思路，能指出两个局限，能想到跨界应用。",
                ["方法思路", "局限", "跨界", "应用"],
            ),
            "pass": None,  # determined by score >= 70
            "note": "满分回答应命中全部关键词，score=100, verdict=通过",
        },
        {
            "id": "eval_grading_surface_answer",
            "input": "问：论文的架构图应该怎么看？学生回答：看图就行了。",
            "expected_keywords": ["数据流", "模块", "连接", "创新点"],
            "actual": grade_answer("看图就行了。", ["数据流", "模块", "连接", "创新点"]),
            "pass": None,
            "note": "表面回答应得低分，触发 missing_points 和追问 next_prompt",
        },
        {
            "id": "eval_multimodal_arch_diagram",
            "input": "图表类型：architecture_diagram。描述：Transformer 架构图，左 Encoder 右 Decoder，中间 Cross-Attention 连接，每层含 Multi-Head Attention + Feed-Forward + LayerNorm。学生问：为什么 Encoder 和 Decoder 之间需要 Cross-Attention？",
            "expected": "输出 input_type='architecture_diagram'，observations 含架构图相关描述，uncertainties 记录信息缺失，agent_context 可交付 Day3。",
            "actual": extract_multimodal_context(
                "architecture_diagram",
                "Transformer 架构图：左 Encoder 右 Decoder，中间 Cross-Attention 连接，每层含 Multi-Head Attention + Feed-Forward + LayerNorm。学生问：为什么 Encoder 和 Decoder 之间需要 Cross-Attention？",
            ),
            "pass": None,
        },
    ]


def render_dashboard(spec: Dict[str, Any], prompt_lib: Dict[str, Any], cards: List[Dict[str, Any]], handoff: Dict[str, Any], cases: List[Dict[str, Any]], day1_brief: Dict[str, Any]) -> str:
    now_str = datetime.now().isoformat(timespec="seconds")
    router = day1_brief.get("router", {})

    # --- Prompt rows ---
    prompt_rows = "".join(
        f"<tr><td><code>{escape(p['id'])}</code></td><td><span class='tag tag-{escape(p['type'])}'>{escape(p['type'])}</span></td><td><b>{escape(p['preferred_model'])}</b></td><td>{escape(p['teaches'])}</td></tr>"
        for p in prompt_lib["prompts"]
    )

    # --- Router rows ---
    router_rows = "".join(
        f"<tr><td><b>{escape(role)}</b></td><td>{escape(rule.get('preferred_model','-'))}</td><td class='s{min(rule.get('score',0),5)}'>{escape(str(rule.get('score','-')))}</td><td style='font-size:12px;color:var(--muted)'>{escape(str(rule.get('fallback_model',rule.get('fallback_rule','-'))))}</td></tr>"
        for role, rule in router.items()
    )

    # --- Action rows ---
    action_rows = "".join(
        f"<tr><td><code>{escape(a['name'])}</code></td><td style='font-size:12px'>{escape(a['input'])}</td><td>{escape(a['output'])}</td><td><code style='font-size:11px'>{escape(a['writes'])}</code></td></tr>"
        for a in handoff["actions"]
    )

    # --- Review cards ---
    card_html = "".join(
        f"""<div class='card'>
  <div style='font-weight:650;margin-bottom:6px'>{escape(c['question'])}</div>
  <div style='color:var(--muted);font-size:13px;margin-bottom:6px'>{escape(c['answer'])}</div>
  <div style='display:flex;flex-wrap:wrap;gap:4px;align-items:center'>{"".join(f"<span class='tag tag-info'>{escape(t)}</span>" for t in c['tags'])}<span style='color:var(--muted);font-size:11px;margin-left:auto'>提示：{escape(c['hint'])}</span></div>
</div>""" for c in cards
    )

    # --- Handoff read-before-run ---
    day3_rbr = handoff.get('day3_contract', {}).get('read_before_run', [])
    handoff_readme = " · ".join(f"<code style='font-size:11px'>{escape(f)}</code>" for f in day3_rbr)

    # --- Eval cases ---
    eval_rows = "".join(
        f"""<div class='card'>
  <div style='font-weight:650;margin-bottom:4px'>{escape(c['id'])} <span class='tag {"tag-pass" if c.get("pass") else "tag-pending"}'>{'通过' if c.get("pass") else '待验证'}</span></div>
  <div style='color:var(--muted);font-size:12px'><b>输入：</b>{escape(str(c.get('input',''))[:120])}</div>
  <div style='color:var(--muted);font-size:12px'><b>期望：</b>{escape(str(c.get('expected',''))[:120])}</div>
  {f"<div style='color:#4caf50;font-size:11px'>{escape(c.get('note',''))}</div>" if c.get('note') else ""}
  <details style='margin-top:6px'><summary style='cursor:pointer;color:var(--accent);font-size:12px'>查看实际输出</summary><pre style='margin-top:4px'>{escape(json.dumps(c.get('actual'), ensure_ascii=False, indent=2)[:600])}</pre></details>
</div>""" for c in cases
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Day2 产品控制台 — {escape(spec['product_name'])}</title>
<style>
:root{{--bg:#0d1117;--card-bg:#161b22;--border:#30363d;--text:#c9d1d9;--muted:#8b949e;--accent:#58a6ff;--g5:#1b5e20;--g4:#4caf50;--g3:#ff9800;--g2:#e65100;--g1:#c62828;--gr:#555}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,sans-serif;line-height:1.55}}
header{{background:var(--card-bg);border-bottom:1px solid var(--border);padding:24px 32px;text-align:center}}
header h1{{font-size:24px;margin-bottom:4px}}
header p{{color:var(--muted);font-size:13px;max-width:800px;margin:4px auto 0}}
main{{max-width:1100px;margin:0 auto;padding:16px}}

.kpi-row{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}}
.kpi{{background:var(--card-bg);border:1px solid var(--border);border-radius:8px;padding:18px;text-align:center}}
.kpi .n{{font-size:34px;font-weight:700;color:var(--accent)}}
.kpi .l{{color:var(--muted);font-size:12px;margin-top:4px}}

section{{margin-bottom:16px}}
.sh{{background:var(--card-bg);border:1px solid var(--border);border-radius:8px 8px 0 0;padding:12px 16px;font-size:16px;font-weight:700;cursor:pointer;user-select:none;display:flex;align-items:center;gap:8px}}
.sh:hover{{background:#1c2129}}
.sb{{background:var(--card-bg);border:1px solid var(--border);border-top:0;border-radius:0 0 8px 8px;padding:16px;overflow-x:auto}}
.sb.hide{{display:none}}

table{{width:100%;border-collapse:collapse;font-size:13px}}
td,th{{border:1px solid var(--border);padding:8px 10px;text-align:left;vertical-align:top}}
th{{background:#1c2129;font-weight:600;white-space:nowrap;text-align:left}}

.tag{{display:inline-block;border-radius:999px;padding:2px 10px;font-size:11px;font-weight:600}}
.tag-system{{background:#1b5e20;color:#a5d6a7}}
.tag-task{{background:#0d47a1;color:#90caf9}}
.tag-repair{{background:#e65100;color:#ffcc80}}
.tag-handoff{{background:#4a148c;color:#ce93d8}}
.tag-info{{background:#1c2129;border:1px solid var(--border);color:var(--muted);border-radius:4px;padding:2px 8px;font-size:11px;font-weight:400}}
.tag-pass{{background:var(--g5);color:#a5d6a7}}
.tag-pending{{background:var(--gr);color:#aaa}}

.s5{{background:var(--g5);color:#c8e6c9;text-align:center}} .s4{{background:var(--g4);color:#000;text-align:center}} .s3{{background:var(--g3);color:#000;text-align:center}} .s2{{background:var(--g2);color:#fff;text-align:center}} .s1{{background:var(--g1);color:#fff;text-align:center}} .s0,.sp{{background:var(--gr);color:#aaa;text-align:center}}

.card{{background:#1c2129;border:1px solid var(--border);border-radius:6px;padding:12px;margin-bottom:10px}}
pre{{white-space:pre-wrap;font-size:12px;max-height:280px;overflow-y:auto;background:#111;padding:8px;border-radius:4px}}
a{{color:var(--accent);text-decoration:none}} a:hover{{text-decoration:underline}}
.chevron{{color:var(--muted);font-size:12px;transition:.2s}}
footer{{text-align:center;color:var(--muted);font-size:11px;padding:16px;border-top:1px solid var(--border);margin-top:16px}}

.g2{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
@media(max-width:768px){{.kpi-row{{grid-template-columns:repeat(2,1fr)}}.g2{{grid-template-columns:1fr}}header{{padding:16px}}}}
</style>
</head>
<body>
<header>
  <h1>Day2 产品控制台</h1>
  <p>{escape(spec['product_name'])} — {escape(spec['one_liner'])}</p>
  <p style="margin-top:6px">6 条 Prompt · 4 个能力定义 · 4 个评测用例 · {len(router)} 个路由角色 | {now_str}</p>
</header>
<main>

<div class="kpi-row">
  <div class="kpi"><div class="n">{len(prompt_lib['prompts'])}</div><div class="l">提示词资产</div></div>
  <div class="kpi"><div class="n">{len(handoff['actions'])}</div><div class="l">能力动作</div></div>
  <div class="kpi"><div class="n">{len(cards)}</div><div class="l">复习卡样例</div></div>
  <div class="kpi"><div class="n">{len(cases)}</div><div class="l">评测用例</div></div>
</div>

<section>
<div class="sh" onclick="this.nextElementSibling.classList.toggle('hide')"><span class="chevron">&#9660;</span> Day1 模型路由表</div>
<div class="sb"><table><tr><th>路由角色</th><th>优先模型</th><th>评分</th><th>兜底规则</th></tr>{router_rows}</table></div>
</section>

<section>
<div class="sh" onclick="this.nextElementSibling.classList.toggle('hide')"><span class="chevron">&#9660;</span> Prompt Library — {len(prompt_lib['prompts'])} 条资产</div>
<div class="sb"><table><tr><th>ID</th><th>类型</th><th>优先模型</th><th>教学点</th></tr>{prompt_rows}</table></div>
</section>

<section>
<div class="sh" onclick="this.nextElementSibling.classList.toggle('hide')"><span class="chevron">&#9660;</span> Day3 Agent Handoff — {len(handoff['actions'])} 个动作</div>
<div class="sb"><table><tr><th>动作名</th><th>输入</th><th>输出</th><th>写入路径</th></tr>{action_rows}</table>
<div style="margin-top:12px;font-size:13px;color:var(--muted)">
  <b>Day3 启动时必读：</b>{handoff_readme}
</div></div>
</section>

<section>
<div class="sh" onclick="this.nextElementSibling.classList.toggle('hide')"><span class="chevron">&#9660;</span> 复习卡样例 — {len(cards)} 张</div>
<div class="sb">{card_html}</div>
</section>

<section>
<div class="sh" onclick="this.nextElementSibling.classList.toggle('hide')"><span class="chevron">&#9660;</span> 评测用例 — {len(cases)} 条</div>
<div class="sb">{eval_rows}</div>
</section>

<section>
<div class="sh" onclick="this.nextElementSibling.classList.toggle('hide')"><span class="chevron">&#9660;</span> 文件证据</div>
<div class="sb">
<div class="g2">
<div class="card"><b>能力定义</b><br><a href="product_spec.json">product_spec.json</a><br><a href="prompt_library.json">prompt_library.json</a><br><a href="eval_cases.json">eval_cases.json</a></div>
<div class="card"><b>Schemas</b><br><a href="schemas/review_card.schema.json">review_card.schema.json</a><br><a href="schemas/answer_grading.schema.json">answer_grading.schema.json</a><br><a href="schemas/multimodal_observation.schema.json">multimodal_observation.schema.json</a></div>
<div class="card"><b>上下文包</b><br><a href="context_pack/day1_model_brief.json">day1_model_brief.json</a><br><a href="context_pack/course_seed.md">course_seed.md</a><br><a href="context_pack/user_scenarios.json">user_scenarios.json</a></div>
<div class="card"><b>Day3 接口</b><br><a href="agent_handoff/day2_agent_contract.json">day2_agent_contract.json</a><br><a href="agent_handoff/day2_to_day3_brief.md">day2_to_day3_brief.md</a><br><a href="engine_run_report.json">engine_run_report.json</a></div>
</div></div>
</section>

<section>
<div class="sh" onclick="this.nextElementSibling.classList.toggle('hide')"><span class="chevron">&#9660;</span> 产品规格</div>
<div class="sb"><pre>{escape(json.dumps(spec, ensure_ascii=False, indent=2)[:4000])}</pre></div>
</section>

</main>
<footer>PaperMindCapabilityModule · Day2 AI Learning Capability Module · {now_str}</footer>
</body>
</html>"""


def run_engine() -> Dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    day1_brief = read_json(DAY1_BRIEF, {"router": {}, "purpose": "Day1 brief not generated yet."})
    spec = product_spec()
    prompt_lib = prompt_library(day1_brief)
    schema_map = schemas()
    day3_context = read_text(DAY3_SUMMARY, 3200)
    course_seed = f"""# PaperMind Course Seed

## Product
{spec['product_name']}：{spec['one_liner']}

## 论文阅读六维能力
1. **摘要提炼** — 从 Abstract/Introduction 提取核心贡献与问题定义
2. **方法提取** — 识别算法名、架构组件、训练策略
3. **术语翻译** — 技术术语保留英文，叙述文本中文化
4. **场景推理** — 判断方法能否部署到移动端、实时场景、跨领域
5. **幻觉检测** — 区分论文实际内容 vs 模型编造的信息
6. **图表理解** — 从架构图/曲线图/表格提取结构化信息

## Day3 Context Preview
{day3_context or 'Day3 Agent Core 尚未运行；Day2 先用论文阅读方法论作为种子资料生成能力模块。'}
"""
    cards = generate_review_cards(course_seed)
    cases = eval_cases(cards)
    handoff = build_agent_handoff(spec)
    report = {
        "generated_at": now(),
        "engine_name": "PaperMindCapabilityModule",
        "product": spec["product_name"],
        "day1_brief_loaded": DAY1_BRIEF.exists(),
        "day3_summary_loaded": DAY3_SUMMARY.exists(),
        "prompt_count": len(prompt_lib["prompts"]),
        "schema_count": len(schema_map),
        "eval_count": len(cases),
        "cards": cards,
        "handoff_contract": handoff,
        "assessment": [
            "是否把提示词变成可复用产品能力。",
            "是否提供JSON Schema和Eval Cases。",
            "是否能被Day3 Agent读取并用于工具/RAG流程。",
        ],
    }

    write_json(OUT / "product_spec.json", spec)
    write_json(OUT / "prompt_library.json", prompt_lib)
    write_json(OUT / "context_pack" / "day1_model_brief.json", day1_brief)
    write_text(OUT / "context_pack" / "course_seed.md", course_seed)
    write_text(
        OUT / "context_pack" / "device_constraints.md",
        "# Device Constraints\n\n- 论文阅读场景以桌面端为主，移动端为辅。\n- 屏幕空间：桌面端可展示论文原文+AI 侧栏；移动端仅展示单张复习卡或短问答。\n- 输入方式：桌面端支持截图/粘贴论文段落；移动端支持拍照上传图表。\n- 多模态输入（论文图表、架构图、公式截图）必须先提取结构化上下文再交给 Agent。\n- 离线场景：复习卡可缓存到本地，无网络时仍可自测。\n- 响应时间：简单问答 < 5 秒，图表分析 < 30 秒。\n",
    )
    write_json(
        OUT / "context_pack" / "user_scenarios.json",
        [
            {"scenario": "初筛论文", "input": "这篇论文的核心贡献是什么？值不值得精读？", "output": "3 句话摘要 + 推荐精读/浏览/跳过"},
            {"scenario": "理解方法", "input": "这个方法具体怎么做的？画个架构图说明", "output": "结构化方法描述 + 架构图关键模块列表"},
            {"scenario": "自测理解", "input": "给我出几道题考考我是否真懂了", "output": "3 道复习题 + 期望答案关键词"},
            {"scenario": "图表提问", "input": "上传架构图/曲线图 → 这个图说明了什么？", "output": "图表类型 → 关键信息 → 一句话结论"},
            {"scenario": "跨界联想", "input": "这个方法能用到我的领域吗？", "output": "适用条件分析 + 可能需要的改动"},
        ],
    )
    for name, schema in schema_map.items():
        write_json(OUT / "schemas" / name, schema)
    write_json(OUT / "eval_cases.json", cases)
    write_json(OUT / "agent_handoff" / "day2_agent_contract.json", handoff)
    write_text(
        OUT / "agent_handoff" / "day2_to_day3_brief.md",
        "# Day2 to Day3 Brief\n\nDay2 已经把 PaperMind 的提示词、上下文、结构化输出、多模态上下文抽取和评测样例封装成能力模块。Day3 的桌面 Agent Core 应读取 `agent_handoff/day2_agent_contract.json`，把这些能力放入本地工具调用、RAG 检索和文件写入流程。\n",
    )
    write_json(OUT / "engine_run_report.json", report)
    html = render_dashboard(spec, prompt_lib, cards, handoff, cases, day1_brief)
    write_text(OUT / "Day2_产品控制台.html", html)
    write_text(OUT / "Day2_产品Demo.html", html)
    write_text(
        OUT / "engineering_critique.md",
        "# Day2 工程评审\n\n- 核心产物是 `PaperMindCapabilityModule`，围绕论文阅读六维能力构建。\n- Prompt Library 覆盖 system/task/repair/handoff 四种类型，模型路由从 Day1 读取。\n- Context Pack 包含论文阅读方法论种子、设备约束、用户场景。\n- Schemas 约束复习卡、评分、多模态上下文和 Agent 交接四类输出格式。\n- Eval Cases 覆盖 schema 完整性、评分准确性（高分/低分两种）、多模态图表抽取。\n- 最大风险仍是模型输出格式漂移，因此必须保留 `repair_json` 提示词和 schema 检查。\n- 多模态上下文先结构化再交给 Agent，Day3 做真正的文件操作和工具调用。\n",
    )
    write_text(OUT / "demo_run_before_day3.txt", "Day2 Engine 已可独立生成复习卡、评分样例和 Day3 handoff 合约。\n")
    write_text(OUT / "demo_run_after_day3.txt", f"Day2 Engine 已读取 Day3 摘要：{bool(day3_context)}\n")
    return report


def main() -> None:
    report = run_engine()
    print(json.dumps({"ok": True, "prompt_count": report["prompt_count"], "eval_count": report["eval_count"], "day1_loaded": report["day1_brief_loaded"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
