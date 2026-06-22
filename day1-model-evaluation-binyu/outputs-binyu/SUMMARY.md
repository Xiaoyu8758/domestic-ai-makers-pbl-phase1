# Day1 评测摘要

# Day1 评测摘要

**论文**: Swift-Net: Power-guided Grouped SRUs for Audio-Visual Speech Separation
**评测时间**: 2026-06-22T14:39:24
**模型数**: 5 | **任务数**: 10 | **总调用**: 50

## 速度排名

| 模型 | 均分 | 平均延迟 | 平均 Token |
|---|---|---|---|
| Qwen-VL-8B (Alibaba) | 4.8 | 6.58s | 1101.1 |
| Qwen2.5-72B (Alibaba) | 2.9 | 7.96s | 556.6 |
| DeepSeek | 2.9 | 9.58s | 770.4 |
| GLM-5.2 (Zhipu) | 2.7 | 29.02s | 1639.2 |
| Kimi-K2.6 (Moonshot) | 4.7 | 118.16s | 4196.3 |

## 能力矩阵

| 模型 | 论文创新点提 | 方法/算法名 | 中文翻译·术 | 场景适配判断 | 幻觉检测·未 | 图表理解·图 | 图表理解·图 | 图表理解·图 | 图表理解·图 | 图表理解·图 |
|---|---|---|---|---|---|---|---|---|---|---|
| DeepSeek | 5 | 4 | 5 | 5 | 5 | 1 | 1 | 1 | 1 | 1 |
| GLM-5.2 (Zhipu) | 5 | 4 | 5 | 5 | 3 | 1 | 1 | 1 | 1 | 1 |
| Kimi-K2.6 (Moonshot) | 5 | 4 | 5 | 5 | 3 | 5 | 5 | 5 | 5 | 5 |
| Qwen-VL-8B (Alibaba) | 4 | 4 | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 5 |
| Qwen2.5-72B (Alibaba) | 5 | 4 | 5 | 5 | 5 | 1 | 1 | 1 | 1 | 1 |

## 路由建议

| 角色 | 主模型 | 兜底模型 | 证据任务 |
|---|---|---|---|
| content_summarizer | DeepSeek | Qwen2.5-72B (Alibaba) | paper_summary_001 |
| info_extractor | Qwen-VL-8B (Alibaba) | Qwen2.5-72B (Alibaba) | paper_methods_002 |
| translator | Qwen-VL-8B (Alibaba) | Qwen2.5-72B (Alibaba) | paper_translate_003 |
| scenario_analyst | Qwen-VL-8B (Alibaba) | DeepSeek | paper_scenario_004 |
| fact_checker | Qwen-VL-8B (Alibaba) | DeepSeek | paper_hallucination_005 |
| multimodal_analyst | N/A | N/A | multimodal_arch_006 |
