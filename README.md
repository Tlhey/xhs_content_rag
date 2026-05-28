# xhs_content_rag

把小红书上关于 AI Agent、找工、编程副业的帖子和评论，从原始 JSON 变成可查询的情报库。核心问题：**用户的真实痛点是什么，能做成什么产品机会。**

---

## 快速开始

```bash
pip install pandas pyarrow openai python-dotenv tqdm duckdb jieba rank-bm25 streamlit
python scripts/run_pipeline.py
python scripts/06_query.py --q "agent项目 写进简历"
streamlit run app/review.py
```

---

## 数据流

```
MediaCrawler（爬虫）
    ↓ JSON
data/raw/
    ↓ 01 标准化
data/processed/items.parquet
    ↓ 02 关键词初筛
    ↓ 03 LLM 抽取
data/processed/knowledge.duckdb
    ↓ 07 生成报告
data/outputs/
```

---

## 目录结构

```
xhs_content_rag/
│
├── app/
│   └── review.py               Streamlit 人工审核界面，按帖子分组打标签
│
├── scripts/
│   ├── run_pipeline.py         入口：一键增量跑完全流程，结果归档到带日期子目录
│   ├── 00_audit_data.py        检查原始数据质量（帖子数、评论数、重复率）
│   ├── 01_normalize.py         把 post/comment 统一成同一结构，输出 items.parquet
│   ├── 02_rule_filter.py       关键词打分，决定哪些条目送给 LLM（省 API 费用）
│   ├── 03_llm_extract.py       LLM 结构化抽取：分类、痛点、工具、机会点，支持断点续跑
│   ├── 04_review_sample.py     分层抽样，生成供人工检查的 review_sample.csv
│   ├── 05_build_db.py          把 parquet 写入 DuckDB（items / extractions / evidence）
│   ├── 06_query.py             BM25 中文关键词搜索
│   └── 07_generate_report.py   生成四份汇总报告 CSV
│
├── prompts/
│   ├── extract_item_v1.txt     03_llm_extract.py 用的 prompt
│   └── desired.md              期望的输出格式说明
│
├── data/
│   ├── raw/                    原始 JSON（别手动改）
│   ├── processed/              中间产物：items.parquet、knowledge.duckdb
│   └── outputs/
│       ├── YYYY-MM-DD/         每次 run_pipeline.py 跑完后的归档快照
│       ├── review_sample.csv   人工审核用，app/review.py 读写这个文件
│       └── *.csv               最新四份报告
│
├── MediaCrawler/               小红书爬虫（独立子项目）
├── .env                        API key，不提交 git
└── README.md
```

### 四份报告说明

| 文件 | 内容 |
|------|------|
| `high_value_items.csv` | 相关度 ≥ 4 的帖子和评论，带摘要和原文链接 |
| `pain_point_summary.csv` | 用户痛点汇总，按出现次数排序 |
| `resource_summary.csv` | 用户提到的工具、平台、资源统计 |
| `agent_opportunity_summary.csv` | 可做成产品功能的机会点，带优先级 |
