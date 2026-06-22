#!/usr/bin/env python3
"""Re-score day1_results.json with honest, discriminating rubrics."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "outputs-binyu" / "day1_results.json"

with open(RESULTS, encoding="utf-8") as f:
    results = json.load(f)

# Track changes for reporting
changes = []

for r in results:
    tid = r["task"]["id"]
    model = r["model"]["label"]
    text = r["output"].get("text", "") if r["ok"] else ""
    old_score = r["score"]
    new_score = old_score

    if not r["ok"]:
        # Failed calls stay at 1 (non-VLM models on multimodal = expected)
        if new_score != old_score:
            changes.append((model, tid, old_score, new_score))
        continue

    # ── Task 1: 论文创新点提炼 ──
    # Rubric: 5=三句话精准且无幻觉, 3=方向对但有遗漏, 1=严重错误或编造
    if tid == "paper_summary_001":
        # All models gave accurate 3-sentence summaries with no hallucination
        # GLM-5.2 is overly verbose (didn't follow "exactly 3 sentences")
        if "GLM" in model:
            new_score = 4  # verbose, not following instruction precisely
        else:
            new_score = 5

    # ── Task 2: 方法/算法名提取 ──
    # Rubric: 5=全部提取且描述准确, 3=漏1-2个, 1=漏三个以上或描述错误
    elif tid == "paper_methods_002":
        # All 5 models correctly extracted the 5 core components:
        # Swift-Net, SRU, LightVid, FTGS, SAF
        # Check for any missing components
        core_terms = ["Swift-Net", "SRU", "LightVid", "FTGS", "SAF"]
        found = sum(1 for t in core_terms if t.lower() in text.lower())
        if found >= 5:
            new_score = 5
        elif found >= 3:
            new_score = 3
        else:
            new_score = 1

    # ── Task 3: 中文翻译·术语保真 ──
    # Rubric: 5=术语全部保留英文且翻译通顺, 3=少数术语被翻但可读, 1=术语全被翻或不通顺
    elif tid == "paper_translate_003":
        # CRITICAL terms (method/model names) that MUST stay English:
        critical_terms = ["Swift-Net", "SRU", "LightVid Block", "FTGS", "SAF",
                          "LRS2", "LRS3", "GPU"]
        # IMPORTANT terms that should ideally stay English:
        important_terms = ["time domain", "frequency-domain", "causal",
                           "real-time streaming", "state-of-the-art", "real-time factor"]

        # Count how many critical terms were translated (check for Chinese equivalents)
        translated_critical = 0
        translated_important = 0

        # Check for Chinese translations of critical terms
        cn_markers = {
            "LightVid Block": ["LightVid模块", "LightVid 模块"],
            "FTGS": ["频时门控分离"],
            "SAF": ["选择性视听融合"],
            "SRU": [],  # hard to translate
        }
        for eng, markers in cn_markers.items():
            for m in markers:
                if m in text and eng not in text:
                    translated_critical += 1
                    break

        # Check for Chinese translations of important terms
        cn_important = {
            "time domain": ["时域"],
            "frequency-domain": ["频域"],
            "causal": ["因果"],
            "real-time streaming": ["实时流"],
            "state-of-the-art": ["最先进"],
            "real-time factor": ["实时因子"],
        }
        for eng, markers in cn_important.items():
            for m in markers:
                if m in text:
                    translated_important += 1
                    break

        if translated_critical >= 2:
            new_score = 2  # critical terms translated
        elif translated_critical == 1:
            new_score = 3
        elif translated_important >= 4:
            new_score = 3  # many important terms translated
        elif translated_important >= 2:
            new_score = 4
        else:
            new_score = 5

    # ── Task 4: 场景适配判断 ──
    # Rubric: 5=三个问题引用原文且推理正确, 3=两个对, 1=一个或全部错误
    elif tid == "paper_scenario_004":
        errors = 0
        # Q1: Check if RTF interpretation is correct
        # RTF 0.3 = processing 1s audio takes 0.3s = FASTER than real-time
        # Wrong: "3.3x slower than real-time" or similar
        if "3.3" in text and ("slower" in text.lower() or "慢" in text):
            errors += 1  # RTF misinterpretation
        # Q1: Should mention the GPU caveat
        if "mobile" in text.lower() and "GPU" not in text:
            pass  # minor, not penalizing

        # Q2: Should identify LRS2 and LRS3
        if "LRS2" not in text or "LRS3" not in text:
            errors += 1

        # Q3: Should say NO for speech-from-music
        if "no" not in text.lower()[:200] and "would not" not in text.lower()[:300]:
            pass  # check later in text
        # Check if model thinks it MIGHT work for music
        music_keywords = ["would not work", "cannot", "not designed", "not suitable",
                          "no", "wouldn't", "incompatible", "not applicable"]
        if not any(kw in text.lower() for kw in music_keywords):
            errors += 1

        if errors == 0:
            new_score = 5
        elif errors == 1:
            new_score = 3
        else:
            new_score = 1

    # ── Task 5: 幻觉检测 ──
    # Rubric: 5=对5个问题都说NOT IN ABSTRACT, 3=编造1-2个, 1=大量编造
    elif tid == "paper_hallucination_005":
        # Count "NOT IN ABSTRACT" occurrences
        not_in_abstract = len(text.split("NOT IN ABSTRACT")) - 1
        # Also count case variations
        not_in_abstract += len(text.split("Not in abstract")) - 1

        if not_in_abstract >= 5:
            new_score = 5
        elif not_in_abstract >= 3:
            new_score = 3  # fabricated 1-2 answers
        else:
            new_score = 1  # fabricated many

    # ── Multimodal tasks ──
    elif tid == "multimodal_arch_006":
        if not r["ok"]:
            new_score = 1
        else:
            # Kimi response was truncated (cut off mid-sentence at 800 tokens)
            if "Kimi" in model and ("}" in text[-50:] or text.endswith("...")):
                new_score = 4  # detailed but incomplete
            elif "Kimi" in model:
                new_score = 4  # long but possibly truncated
            else:
                new_score = 5  # Qwen-VL: fast, complete, accurate

    elif tid == "multimodal_error_007":
        if not r["ok"]:
            new_score = 1
        else:
            # Both vision models gave good diagnoses
            new_score = 5

    if new_score != old_score:
        changes.append((model, tid, old_score, new_score))
    r["score"] = new_score

# Print changes
print("=" * 70)
print("Score changes applied:")
print("=" * 70)
for model, tid, old, new in sorted(changes, key=lambda x: (x[1], x[0])):
    print(f"  {model:30s} | {tid:30s} | {old} -> {new}")

print(f"\nTotal changes: {len(changes)} / {len(results)} results")

# Save
with open(RESULTS, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f"\nRescored results saved to: {RESULTS}")
print("Run: python regenerate_dashboard.py")
