# Day1 论文阅读理解能力自动化评测

输入一篇 arXiv 论文 ID，自动抓取元数据、提取架构图、生成评测题、调用多模态 LLM 打分、输出完整评测报告。

## 快速开始

```bash
# 1. 安装依赖
pip install requests PyMuPDF

# 2. 配置 API Key（硅基流动）
# 确保 ../resources/local_siliconflow.env 文件存在，内容：
# SILICONFLOW_API_KEY=你的key
# SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1

# 3. 一键评测
python auto_pipeline.py --arxiv 2506.06689
```

换论文只需改 arXiv ID：
```bash
python auto_pipeline.py --arxiv 2309.17189
```

## 评测什么

对比 5 个大模型在 **论文阅读理解** 的 5 个维度 + 1 个多模态能力：

| 能力维度 | 任务 | 考什么 |
|---|---|---|
| 创新提炼 | 用 3 句话总结论文贡献 | 文献调研、摘要生成 |
| 方法提取 | 识别所有算法/架构组件名 | 技术选型方案设计 |
| 术语翻译 | 中译英时保留技术术语不翻译 | 技术文档本地化 |
| 场景推理 | 判断方法能否落地移动端/跨领域 | 工程可行性判断 |
| 幻觉诚实度 | 对于摘要未提及的信息是否编造 | 安全底线 |
| 图表理解 | 描述架构图的结构和关键信息 | 论文复现 |

## 工作流（6 步）

```
--arxiv 2506.06689
       │
  Step 1  抓 arXiv 元数据        → 标题、摘要、PDF链接
  Step 2  下载 PDF + 切架构图    → paper.pdf + 5 张架构图 PNG
  Step 3  AI 动态出题            → 5 道文本题 + 5 道多模态题
  Step 4  调 5 个模型 API 打分   → 55 次 API 调用
  Step 5  自适应评分             → 关键术语自动提取，参数化评分
  Step 6  生成全部产物           → Dashboard + 9 个交付物文件
```

### 架构图怎么切的

PyMuPDF 定位论文中 "Figure N" 图注文字 → 合并图注上方所有矢量绘图的外接矩形 → 3x 放大渲染 → 保存为独立 PNG。这套方法能捕获 LaTeX 绘制的矢量架构图（`extract_image()` 拿不到）。

## 产物文件

```
outputs-binyu/
├── Dashboard.html                 ← 可视化评测报告（用 HTTP 打开）
├── day1_results.json              ← 原始 55 条 API 调用结果
├── day1_to_day2_brief.json        ← → Day2 模型路由规则
├── model_capability_matrix.json   ← 模型能力矩阵 + 排名榜
├── model_pool_policy.json         ← 模型池选择策略
├── model_selection_playbook.md    ← 选型原则手册
├── failure_casebook.md            ← 失败/风险样本分析
├── student_task_cards.md          ← 学生任务卡
├── SUMMARY.md                     ← 一页评测摘要
├── paper.pdf                      ← 原始论文 PDF
└── figures/
    ├── figure_1_arch.png          ← Figure 1: Causal pooling 示意图
    ├── figure_2_arch.png          ← Figure 2: Swift-Net 整体架构
    ├── figure_3_arch.png          ← Figure 3: LightVid Block 结构
    ├── figure_4_arch.png          ← Figure 4: FTGS Block 结构
    └── figure_5_arch.png          ← Figure 5: SAF Block 结构
```

### 怎么打开 Dashboard

**不要双击 HTML**（file:// 协议会阻止 CDN 加载 Chart.js）。用 HTTP 服务：

```bash
cd outputs-binyu
python -m http.server 8766
# 浏览器打开 http://127.0.0.1:8766/Dashboard.html
```

## 命令行参数

| 参数 | 说明 | 默认值 |
|---|---|---|
| `--arxiv` | arXiv 论文 ID | 必填 |
| `--models` | 评测模型数量 (1-5) | 5 |
| `--no-dashboard` | 跳过 Dashboard 生成 | false |
| `--skip-fetch` | 跳过 arXiv 抓取，用缓存 | false |
| `--output-dir` | 输出目录 | outputs-binyu |

## 项目文件

| 文件 | 职责 |
|---|---|
| `auto_pipeline.py` | 总入口，6 步编排 (~820 lines) |
| `paper_tools.py` | arXiv 抓取 + PDF 架构图切块 + 关键术语提取 |
| `deliverables.py` | 8 个交付物自动生成器 |
| `run_full_pipeline.py` | 原始硬编码管线（保留） |
| `build_dashboard.py` | 原始 Dashboard 生成器（保留） |
| `serve.py` | 本地 HTTP 静态文件服务 |

## Day1 → Day2 关系

Day1 评测出"哪个模型适合哪个论文阅读任务"，`day1_to_day2_brief.json` 把这个结论编码为 6 个路由角色：

```
content_summarizer → 最佳模型: Qwen-VL-8B
info_extractor      → 最佳模型: Qwen2.5-72B
translator          → 最佳模型: Qwen-VL-8B
scenario_analyst    → 最佳模型: Qwen-VL-8B
fact_checker        → 最佳模型: Qwen-VL-8B
multimodal_analyst  → 最佳模型: Qwen-VL-8B
```

Day2 直接读取这个文件，把不同论文阅读任务路由到最合适的模型。

## 依赖

- Python 3.9+
- requests — arXiv API + SiliconFlow API
- PyMuPDF — PDF 解析 + 架构图提取 + 页面渲染
- Chart.js — Dashboard 图表（CDN 加载，无需安装）
