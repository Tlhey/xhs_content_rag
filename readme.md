# xhs_content_rag

小红书求职 / AI Agent 内容结构化情报系统。

原始数据：80 posts, 766 comments（来源关键词：agent / agent项目 / 编程副业 / 编程兼职）

---

## 流程

```
原始 JSON → 清洗标准化 → 规则初筛 → LLM 抽取 → 结构化 DB → 检索 → RAG 问答
```

---

## TODO

### 数据清理（已完成）
- [x] `00_audit_data.py` — 审计字段、重复、交集
- [x] `01_normalize.py` — 统一 post/comment 格式，去重，输出 items.parquet
- [x] `02_rule_filter.py` — 关键词初筛，打 rule_score / should_send_to_llm

**当前结果：** 831 items，215 条（25.9%）进入 LLM 阶段

### LLM 抽取
- [ ] `prompts/extract_item_v1.txt` — 固定 JSON 输出格式的 prompt
- [ ] `03_llm_extract.py` — 批量抽取，输出 extracted_items.parquet
- [ ] `04_review_sample.py` — 抽样人工检查

### 结构化入库
- [ ] 写入 DuckDB（items / extractions / evidence 三张表）

### 统计输出
- [ ] `07_generate_report.py` — 生成四个 CSV
  - `high_value_items.csv`（relevance ≥ 4）
  - `resource_summary.csv`
  - `pain_point_summary.csv`
  - `agent_opportunity_summary.csv`

### 检索
- [ ] `06_query.py` — BM25 关键词检索
- [ ] 向量检索（faiss）
- [ ] 混合排序

### RAG 问答
- [ ] `prompts/summarize_query_v1.txt`
- [ ] CLI 接口 `app/cli.py`

---

## 目录结构

```
data/
  raw/          原始 JSON
  processed/    parquet + duckdb
  outputs/      CSV 报告
scripts/        00~07 处理流水线
prompts/        LLM prompt 模板
app/            cli.py
```
