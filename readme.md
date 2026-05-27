# xhs_content_rag

把小红书上关于 AI Agent、找工、编程副业的帖子和评论，从一堆杂乱的 JSON 变成可以检索、分析、查询的情报库。

核心问题是：用户在这件事上的真实痛点是什么？他们想要什么？能做成什么产品功能？

---

## 现在有什么数据

| 批次 | 来源关键词 | 帖子 | 评论 |
|------|-----------|------|------|
| 2026-05-26 | agent / agent项目 / 编程副业 / 编程兼职 | 80 | 766 |
| 2026-05-27 | agent实战 / MCP项目 / AI工作流项目 / 企业agent / agent案例 | 100 | 1986 |

---

## 快速开始

```bash
# 安装依赖
pip install pandas pyarrow openai python-dotenv tqdm duckdb jieba rank-bm25

# 配置 API key（已有 .env 文件，填入就行）
# MINIMAX_API_KEY=...
# MINIMAX_BASE_URL=https://api.minimaxi.com/v1
# MINIMAX_MODEL=MiniMax-M2.7

# 有新爬虫数据时，一条命令跑完全流程
python scripts/run_pipeline.py

# 搜索
python scripts/06_query.py --q "agent项目 写进简历"
```

---

## 有新数据怎么办

1. 把新文件放进 `MediaCrawler/data/xhs/json/`，命名格式 `search_contents_YYYY-MM-DD.json`
2. 运行 `python scripts/run_pipeline.py`
3. 完成后在 `data/outputs/YYYY-MM-DD/` 找报告

pipeline 会自动跳过已经处理过的数据，只处理新增部分。

---

## 每个脚本是干什么的

**`00_audit_data.py` — 看数据质量**

跑完能知道有多少帖子、多少评论、有没有重复、有没有空内容。每次拿到新数据先跑这个，确认数据没问题再继续。

```bash
python scripts/00_audit_data.py
```

---

**`01_normalize.py` — 统一格式**

原始 JSON 里 post 和 comment 的字段完全不一样，这一步把它们变成统一的结构，方便后续处理。同时去掉用户 ID、头像等隐私字段，把"1.2万"这类字符串转成数字，给评论补上它所属帖子的标题和链接。

输出：`data/processed/items.parquet`（post + comment 合并，2671 条）

```bash
python scripts/01_normalize.py          # 增量，只加新数据
python scripts/01_normalize.py --full   # 全量重建
```

---

**`02_rule_filter.py` — 关键词初筛**

不是所有内容都值得花 API 费用让 LLM 分析。这一步用关键词词典给每条内容打分，只把真正相关的送给 LLM。比如同时提到"agent"和"实习"的就高优先级，只说"老公"、"穿搭"的就跳过。

结果写回 `items.parquet`，新增 `rule_score`、`rule_labels`、`should_send_to_llm` 三列。目前 2671 条里有 683 条会送 LLM。

```bash
python scripts/02_rule_filter.py
```

---

**`03_llm_extract.py` — LLM 结构化抽取**

把每条内容送给 MiniMax，让它输出固定格式的 JSON：这条内容属于哪个分类、有什么痛点、提到了什么工具、有什么可以做成产品功能的机会点。

支持断点续跑，中断后重新执行会自动跳过已经处理的条目。用 3 个并发，速度比串行快 3 倍。

```bash
python scripts/03_llm_extract.py                # 全量跑
python scripts/03_llm_extract.py --limit 10     # 只跑 10 条测试
python scripts/03_llm_extract.py --retry        # 重跑上次失败的
```

---

**`04_review_sample.py` — 抽样人工检查**

LLM 不是每次都对。这一步按相关度分层抽样，生成一个 CSV，让你快速检查 LLM 分类得准不准。

```bash
python scripts/04_review_sample.py
# 输出到 data/outputs/review_sample.csv
# 在 CSV 里填 human_check = good / bad / unsure
```

---

**`05_build_db.py` — 写入 DuckDB**

把 parquet 里的数据整理成三张关系表写进数据库，方便后续的统计查询。

- `items` — 所有帖子和评论
- `extractions` — LLM 抽取结果
- `evidence` — 原文证据句

```bash
python scripts/05_build_db.py           # 增量
python scripts/05_build_db.py --full    # 全量重建
```

---

**`06_query.py` — 关键词搜索**

用 BM25 在数据库里搜索，支持中文分词。标题和摘要权重比正文高，相关度分数也会影响排序。

```bash
python scripts/06_query.py --q "AI产品经理 实习 面试"
python scripts/06_query.py --q "不会Python 能做Agent项目吗" --top 10
python scripts/06_query.py --q "agent项目推荐" --min-score 4
```

---

**`07_generate_report.py` — 生成四个报告**

从数据库里统计出四份 CSV，是整个 pipeline 最终的产出：

| 文件 | 内容 |
|------|------|
| `high_value_items.csv` | 相关度 ≥ 4 的高价值帖子和评论，每条都有摘要和原文链接 |
| `pain_point_summary.csv` | 用户痛点汇总，按出现次数排序 |
| `resource_summary.csv` | 用户提到的工具、平台、资源统计 |
| `agent_opportunity_summary.csv` | 可以做成产品功能的机会点，带优先级 |

```bash
python scripts/07_generate_report.py
```

---

**`run_pipeline.py` — 一键跑完整流程**

把上面所有步骤串起来，自动检测有没有新数据或未处理的条目，只做增量处理。跑完后把报告归档到带日期的子目录。

```bash
python scripts/run_pipeline.py                  # 正常模式
python scripts/run_pipeline.py --no-llm         # 跳过 LLM（快速看数据量）
python scripts/run_pipeline.py --full-rebuild   # 全量重建
python scripts/run_pipeline.py --sync-only      # 只同步文件不跑处理
```

---

## 目录结构

```
xhs_content_rag/
├── data/
│   ├── raw/                    原始 JSON，别手动改
│   ├── processed/              中间产物（parquet、duckdb）
│   └── outputs/
│       ├── 2026-05-27/         带日期的历史报告
│       └── *.csv               最新报告
├── scripts/
│   ├── run_pipeline.py         入口，一键跑
│   ├── 00_audit_data.py
│   ├── 01_normalize.py
│   ├── 02_rule_filter.py
│   ├── 03_llm_extract.py
│   ├── 04_review_sample.py
│   ├── 05_build_db.py
│   ├── 06_query.py
│   └── 07_generate_report.py
├── prompts/
│   └── extract_item_v1.txt     LLM 抽取的 prompt
├── MediaCrawler/               小红书爬虫（独立子项目）
├── .env                        API key，不提交 git
└── readme.md
```
