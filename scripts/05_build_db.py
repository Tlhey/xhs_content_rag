"""写入 DuckDB：items / extractions / evidence 三张表。

用法：
    python scripts/05_build_db.py          # 增量：只插入新 item_id
    python scripts/05_build_db.py --full   # 全量重建
"""
import argparse
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
PROCESSED = ROOT / "data" / "processed"
DB_PATH = PROCESSED / "knowledge.duckdb"


def to_json_str(val) -> str:
    if val is None:
        return "[]"
    if isinstance(val, (list, np.ndarray)):
        return json.dumps(list(val), ensure_ascii=False)
    if isinstance(val, str):
        return val
    return json.dumps(val, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()

    con = duckdb.connect(str(DB_PATH))

    if args.full:
        con.execute("DROP TABLE IF EXISTS evidence")
        con.execute("DROP TABLE IF EXISTS extractions")
        con.execute("DROP TABLE IF EXISTS items")

    # ── items 表 ──────────────────────────────────────────────
    con.execute("""
        CREATE TABLE IF NOT EXISTS items (
            item_id          TEXT PRIMARY KEY,
            source_type      TEXT,
            note_id          TEXT,
            comment_id       TEXT,
            title            TEXT,
            text             TEXT,
            parent_note_title TEXT,
            source_keyword   TEXT,
            tag_list         TEXT,
            like_count       INTEGER,
            collect_count    INTEGER,
            comment_count    INTEGER,
            share_count      INTEGER,
            note_url         TEXT,
            created_at       TEXT,
            rule_score       DOUBLE,
            rule_labels      TEXT,
            should_send_to_llm BOOLEAN
        )
    """)

    items = pd.read_parquet(PROCESSED / "items.parquet")
    existing_items = set(con.execute("SELECT item_id FROM items").fetchdf()["item_id"])
    new_items = items[~items["item_id"].isin(existing_items)].drop_duplicates("item_id").copy()

    if len(new_items):
        for col in ["title", "parent_note_title", "source_keyword", "tag_list", "note_url", "created_at", "rule_labels"]:
            new_items[col] = new_items[col].fillna("").astype(str)
        for col in ["like_count", "collect_count", "comment_count", "share_count"]:
            new_items[col] = pd.to_numeric(new_items[col], errors="coerce").fillna(0).astype(int)
        con.execute("INSERT INTO items SELECT item_id,source_type,note_id,comment_id,title,text,parent_note_title,source_keyword,tag_list,like_count,collect_count,comment_count,share_count,note_url,created_at,rule_score,rule_labels,should_send_to_llm FROM new_items")
        print(f"items: inserted {len(new_items)} new rows (total {len(items)})")
    else:
        print(f"items: nothing new (total {len(items)})")

    # ── extractions 表 ────────────────────────────────────────
    con.execute("""
        CREATE TABLE IF NOT EXISTS extractions (
            item_id              TEXT PRIMARY KEY,
            is_relevant          BOOLEAN,
            relevance_score      INTEGER,
            main_category        TEXT,
            sub_categories       TEXT,
            summary              TEXT,
            resources            TEXT,
            tools                TEXT,
            platforms            TEXT,
            roles                TEXT,
            pain_points          TEXT,
            user_needs           TEXT,
            agent_opportunities  TEXT,
            project_ideas        TEXT,
            evidence_sentence    TEXT,
            actionability_score  INTEGER,
            confidence           DOUBLE,
            parse_failed         BOOLEAN
        )
    """)

    ext = pd.read_parquet(PROCESSED / "extracted_items.parquet")
    existing_ext = set(con.execute("SELECT item_id FROM extractions").fetchdf()["item_id"])
    new_ext = ext[~ext["item_id"].isin(existing_ext)].drop_duplicates("item_id").copy()

    if len(new_ext):
        for col in ["sub_categories", "resources", "tools", "platforms", "roles",
                    "pain_points", "user_needs", "agent_opportunities", "project_ideas"]:
            new_ext[col] = new_ext[col].apply(to_json_str)
        for col in ["summary", "evidence_sentence", "main_category"]:
            new_ext[col] = new_ext[col].fillna("").astype(str)
        new_ext["relevance_score"] = pd.to_numeric(new_ext["relevance_score"], errors="coerce").fillna(0).astype(int)
        new_ext["actionability_score"] = pd.to_numeric(new_ext["actionability_score"], errors="coerce").fillna(0).astype(int)
        con.execute("INSERT INTO extractions SELECT item_id,is_relevant,relevance_score,main_category,sub_categories,summary,resources,tools,platforms,roles,pain_points,user_needs,agent_opportunities,project_ideas,evidence_sentence,actionability_score,confidence,parse_failed FROM new_ext")
        print(f"extractions: inserted {len(new_ext)} new rows")
    else:
        print(f"extractions: nothing new")

    # ── evidence 表 ───────────────────────────────────────────
    con.execute("""
        CREATE TABLE IF NOT EXISTS evidence (
            evidence_id      TEXT PRIMARY KEY,
            item_id          TEXT,
            evidence_sentence TEXT,
            main_category    TEXT,
            relevance_score  INTEGER,
            actionability_score INTEGER,
            source_type      TEXT,
            note_url         TEXT
        )
    """)

    existing_ev = set(con.execute("SELECT evidence_id FROM evidence").fetchdf()["evidence_id"])
    ev_rows = []
    for _, row in ext[(ext["parse_failed"] == False) & (ext["evidence_sentence"].fillna("") != "")].iterrows():
        eid = f"ev:{row['item_id']}"
        if eid not in existing_ev:
            item_row = items[items["item_id"] == row["item_id"]]
            ev_rows.append({
                "evidence_id": eid,
                "item_id": row["item_id"],
                "evidence_sentence": str(row.get("evidence_sentence", "")),
                "main_category": str(row.get("main_category", "")),
                "relevance_score": int(row.get("relevance_score", 0) or 0),
                "actionability_score": int(row.get("actionability_score", 0) or 0),
                "source_type": item_row["source_type"].values[0] if len(item_row) else "",
                "note_url": item_row["note_url"].values[0] if len(item_row) else "",
            })
    if ev_rows:
        ev_df = pd.DataFrame(ev_rows).drop_duplicates("evidence_id")
        con.execute("INSERT INTO evidence SELECT * FROM ev_df")
        print(f"evidence: inserted {len(ev_rows)} new rows")
    else:
        print("evidence: nothing new")

    # 打印汇总
    print()
    for tbl in ["items", "extractions", "evidence"]:
        n = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        print(f"  {tbl:15s} {n} rows")

    con.close()
    print(f"\nsaved → {DB_PATH}")


if __name__ == "__main__":
    main()
