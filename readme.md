# xhs_content_rag

小红书求职 / AI Agent 内容结构化情报系统。

原始数据：80 posts，766 comments（关键词：agent / agent项目 / 编程副业 / 编程兼职）

---

## 整体流程

```
原始 JSON
  → 00 审计
  → 01 标准化 + 去重
  → 02 规则初筛
  → 03 LLM 结构化抽取        ← 正在进行
  → 04 人工抽样检查
  → 05 写入 DuckDB
  → 06 关键词 / 向量检索
  → 07 统计报告输出
  → app RAG 问答 CLI
```

---

## 环境准备

```bash
# 在项目根目录激活虚拟环境
source .venv/bin/activate

# 安装依赖（首次）
pip install pandas pyarrow openai python-dotenv tqdm
pip install duckdb jieba rank-bm25 scikit-learn   # 检索阶段再装
pip install faiss-cpu                              # 向量检索阶段再装
```

`.env` 文件（已配置好）：

```
MINIMAX_API_KEY=sk-...
MINIMAX_BASE_URL=https://api.minimaxi.com/v1
MINIMAX_MODEL=MiniMax-M2.7
```

---

## Step 0 — 放入原始数据

原始文件已复制到：

```
data/raw/search_contents_2026-05-26.json    # 80 条 post
data/raw/search_comments_2026-05-26.json    # 766 条 comment
```

原始来源：`MediaCrawler/data/xhs/json/`

---

## Step 1 — 数据审计 `00_audit_data.py`

**作用：** 确认字段完整性、重复数量、post/comment 的 note_id 交集。

```bash
python scripts/00_audit_data.py
```

**期望输出：**

```
posts rows:              80
comments rows:           766
unique post note_id:     65
unique comment note_id:  65
note_id intersection:    65
duplicate posts:         15        ← 同一帖被不同关键词重复抓
empty title:             0
empty desc:              0
empty comment content:   4
source_keyword distribution:
  'agent'               20
  'agent 项目'            20
  '编程副业'               20
  '编程兼职'               20
```

**检查点：** intersection = 65，说明所有评论都能找到对应帖子，数据可以正常关联。

---

## Step 2 — 标准化 `01_normalize.py`

**作用：**
- 统一 post 和 comment 的字段格式
- 去除隐私字段（user_id / nickname / avatar / xsec_token）
- comment 通过 note_id 关联父帖，补上 parent_note_title / parent_note_desc / source_keyword / note_url
- 处理 "1.2万" 这类字符串数字
- post 按 note_id 去重（65 条唯一）
- 输出三个 parquet

```bash
python scripts/01_normalize.py
```

**输出文件：**

```
data/processed/posts.parquet      80 行（含重复）
data/processed/comments.parquet   766 行
data/processed/items.parquet      831 行（65 post + 766 comment）
```

**检查：**

```python
import pandas as pd
df = pd.read_parquet("data/processed/items.parquet")
print(df.columns.tolist())
print(df[["item_id","source_type","title","text","like_count"]].head(3))
```

---

## Step 3 — 规则初筛 `02_rule_filter.py`

**作用：** 用关键词给每条 item 打分，决定是否送 LLM，减少 token 消耗。

每条 item 会新增三个字段：

| 字段 | 说明 |
|------|------|
| `rule_score` | 整数，越高越相关 |
| `rule_labels` | 命中的标签，逗号分隔（career / agent / resource / pain_point / noise / too_short） |
| `should_send_to_llm` | True/False |

```bash
python scripts/02_rule_filter.py
```

**输出：** 直接覆盖更新 `data/processed/items.parquet`

**期望输出：**

```
total items:        831
should_send_to_llm: 215  (25.9%)

rule_labels distribution:
  agent               186
  resource            126
  too_short           124
  career               88
  pain_point           74
  noise                 1
```

**检查：**

```python
import pandas as pd
df = pd.read_parquet("data/processed/items.parquet")
print(df[df["should_send_to_llm"]==True][["text","rule_score","rule_labels"]].head(5))
```

---

## Step 4 — LLM 抽取 `03_llm_extract.py`  ← 当前步骤（运行中）

**作用：** 对 should_send_to_llm=True 的 215 条 item 调用 MiniMax，输出结构化 JSON。

每条抽取字段：

```
is_relevant / relevance_score(0-5) / main_category / sub_categories
summary / resources / tools / platforms / roles
pain_points / user_needs / agent_opportunities / project_ideas
evidence_sentence / actionability_score(0-5) / confidence
```

**运行方式：**

```bash
# 全量运行（215 条，约 2~3 小时，支持断点续跑）
python scripts/03_llm_extract.py

# 测试：只跑前 5 条看格式是否正确
python scripts/03_llm_extract.py --limit 5

# 重跑上次 parse_failed 的条目
python scripts/03_llm_extract.py --retry
```

**断点续跑机制：** 每处理一条立即 append 写入 jsonl，中断后重跑会自动跳过已完成的 item_id。

**输出文件：**

```
data/processed/extracted_items.jsonl    每行一条，逐条追加
data/processed/extracted_items.parquet  全量完成后生成
```

**检查进度：**

```bash
# 看已完成多少条
wc -l data/processed/extracted_items.jsonl

# 看最新几条的抽取结果
tail -3 data/processed/extracted_items.jsonl | python3 -m json.tool
```

**检查质量（完成后）：**

```python
import pandas as pd
df = pd.read_parquet("data/processed/extracted_items.parquet")
print(df["relevance_score"].value_counts().sort_index())
print(df["main_category"].value_counts())
print(df["parse_failed"].sum(), "条解析失败")
```

---

## Step 5 — 人工抽样检查 `04_review_sample.py`

**作用：** 按 relevance_score 分层抽样，生成 CSV 供人工确认分类是否准确。

```bash
python scripts/04_review_sample.py
```

**输出：** `data/outputs/review_sample.csv`

抽样规则：
- relevance_score = 5 → 随机 30 条
- relevance_score = 4 → 随机 30 条
- relevance_score = 3 → 随机 30 条
- relevance_score ≤ 2 → 随机 30 条
- parse_failed → 全部输出

**人工填写两列：**

```
human_check = good / bad / unsure
human_note  = 如果 bad，写错在哪里
```

---

## 待完成步骤

### Step 6 — 写入 DuckDB

```bash
# 脚本待写：scripts/05_build_db.py
```

三张表：`items` / `extractions` / `evidence`

### Step 7 — 关键词检索

```bash
# 脚本待写：scripts/06_query.py
python scripts/06_query.py --q "AI产品经理 实习 面试"
```

### Step 8 — 统计报告

```bash
# 脚本待写：scripts/07_generate_report.py
python scripts/07_generate_report.py
```

输出四个 CSV：

```
data/outputs/high_value_items.csv         relevance≥4 的高价值内容
data/outputs/resource_summary.csv         资源频次统计
data/outputs/pain_point_summary.csv       痛点频次统计
data/outputs/agent_opportunity_summary.csv 产品机会统计
```

### Step 9 — RAG 问答 CLI

```bash
# 脚本待写：app/cli.py
python app/cli.py
# /search AI产品经理实习
# /report pain_points
```

---

## 目录结构

```
xhs_content_rag/
  data/
    raw/                原始 JSON（勿修改）
    processed/          parquet + duckdb（脚本自动生成）
    outputs/            CSV 报告（脚本自动生成）
  scripts/
    00_audit_data.py    ✅ 数据审计
    01_normalize.py     ✅ 标准化 + 去重
    02_rule_filter.py   ✅ 规则初筛
    03_llm_extract.py   ✅ LLM 抽取（运行中）
    04_review_sample.py ✅ 抽样检查
    05_build_db.py      ⬜ DuckDB 入库
    06_query.py         ⬜ 关键词检索
    07_generate_report.py ⬜ 统计报告
  prompts/
    extract_item_v1.txt   ✅ 抽取 prompt
    summarize_query_v1.txt ⬜ RAG 问答 prompt
  app/
    cli.py              ⬜ 问答 CLI
  .env                  API key（不提交 git）
  readme.md
```
