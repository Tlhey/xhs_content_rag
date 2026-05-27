"""关键词检索：BM25 搜索 items + extractions，返回排序结果。

用法：
    python scripts/06_query.py --q "AI产品经理 实习 面试"
    python scripts/06_query.py --q "agent项目 写进简历" --top 10
    python scripts/06_query.py --q "不会Python 能做AI项目吗" --min-score 3
"""
import argparse
import json
from pathlib import Path

import duckdb
import jieba
import pandas as pd
from rank_bm25 import BM25Okapi

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "processed" / "knowledge.duckdb"


def tokenize(text: str) -> list[str]:
    return [t for t in jieba.cut(str(text)) if len(t.strip()) > 1]


def load_search_corpus(con, min_relevance: int = 0) -> pd.DataFrame:
    df = con.execute(f"""
        SELECT
            e.item_id,
            e.main_category,
            e.relevance_score,
            e.actionability_score,
            e.summary,
            e.evidence_sentence,
            e.pain_points,
            e.agent_opportunities,
            e.resources,
            e.tools,
            i.source_type,
            i.parent_note_title,
            i.text,
            i.note_url,
            i.like_count
        FROM extractions e
        JOIN items i ON e.item_id = i.item_id
        WHERE e.parse_failed = false
          AND e.relevance_score >= {min_relevance}
        ORDER BY e.relevance_score DESC, e.actionability_score DESC
    """).fetchdf()
    return df


def build_doc_text(row: dict) -> str:
    """把各字段拼成一个可检索的文本，标题/摘要权重更高（重复）。"""
    parts = [
        str(row.get("parent_note_title") or ""),
        str(row.get("summary") or ""),
        str(row.get("parent_note_title") or ""),   # 标题加权
        str(row.get("summary") or ""),              # 摘要加权
        str(row.get("text") or "")[:200],
        str(row.get("evidence_sentence") or ""),
        str(row.get("pain_points") or ""),
        str(row.get("agent_opportunities") or ""),
        str(row.get("resources") or ""),
        str(row.get("tools") or ""),
    ]
    return " ".join(p for p in parts if p)


def search(query: str, top_n: int = 10, min_relevance: int = 0) -> pd.DataFrame:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    corpus_df = load_search_corpus(con, min_relevance)
    con.close()

    if corpus_df.empty:
        print("数据库为空，请先运行 05_build_db.py")
        return pd.DataFrame()

    docs = corpus_df.to_dict("records")
    tokenized_docs = [tokenize(build_doc_text(d)) for d in docs]
    bm25 = BM25Okapi(tokenized_docs)

    query_tokens = tokenize(query)
    scores = bm25.get_scores(query_tokens)

    corpus_df["bm25_score"] = scores
    corpus_df["final_score"] = (
        0.5 * corpus_df["bm25_score"] / (corpus_df["bm25_score"].max() + 1e-9)
        + 0.3 * corpus_df["relevance_score"] / 5.0
        + 0.2 * corpus_df["actionability_score"] / 5.0
    )

    results = corpus_df.nlargest(top_n, "final_score")
    return results


def print_results(results: pd.DataFrame, query: str):
    print(f"\n搜索：「{query}」  共 {len(results)} 条结果\n")
    print("─" * 70)
    for rank, (_, row) in enumerate(results.iterrows(), 1):
        title = row.get("parent_note_title") or row.get("text", "")[:40]
        print(f"#{rank}  [{row['source_type']}]  relevance={int(row['relevance_score'])}  action={int(row['actionability_score'])}")
        print(f"    标题：{str(title)[:60]}")
        print(f"    分类：{row['main_category']}")
        print(f"    摘要：{str(row['summary'])[:80]}")
        if row.get("evidence_sentence"):
            print(f"    证据：{str(row['evidence_sentence'])[:80]}")
        if row.get("note_url"):
            print(f"    链接：{row['note_url']}")
        print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--q", required=True, help="搜索关键词")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--min-score", type=int, default=0, dest="min_score")
    args = parser.parse_args()

    results = search(args.q, top_n=args.top, min_relevance=args.min_score)
    if not results.empty:
        print_results(results, args.q)


if __name__ == "__main__":
    main()
