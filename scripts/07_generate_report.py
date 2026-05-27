"""生成四个统计报告 CSV。

用法：
    python scripts/07_generate_report.py
"""
import json
from collections import Counter
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "processed" / "knowledge.duckdb"
OUTPUTS = ROOT / "data" / "outputs"
OUTPUTS.mkdir(parents=True, exist_ok=True)


def load(con) -> tuple[pd.DataFrame, pd.DataFrame]:
    items = con.execute("SELECT * FROM items").fetchdf()
    ext = con.execute("SELECT * FROM extractions WHERE parse_failed = false").fetchdf()
    return items, ext


def parse_list(val) -> list[str]:
    if val is None:
        return []
    if isinstance(val, list):
        return val
    try:
        parsed = json.loads(str(val))
        return [str(x) for x in parsed] if isinstance(parsed, list) else []
    except Exception:
        return []


# ── 1. high_value_items ───────────────────────────────────────────────────────
def report_high_value(items: pd.DataFrame, ext: pd.DataFrame):
    merged = ext.merge(
        items[["item_id", "source_type", "parent_note_title", "text", "note_url", "like_count"]],
        on="item_id", how="left"
    )
    hv = merged[
        (merged["relevance_score"] >= 4) & (merged["actionability_score"] >= 3)
    ].copy()
    hv = hv.sort_values(["relevance_score", "actionability_score", "like_count"], ascending=False)
    hv["rank"] = range(1, len(hv) + 1)

    out = hv[[
        "rank", "item_id", "source_type", "parent_note_title", "summary",
        "main_category", "relevance_score", "actionability_score",
        "resources", "pain_points", "agent_opportunities",
        "evidence_sentence", "note_url"
    ]].reset_index(drop=True)

    path = OUTPUTS / "high_value_items.csv"
    out.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"high_value_items.csv  {len(out)} 条  → {path}")
    return out


# ── 2. resource_summary ───────────────────────────────────────────────────────
def report_resources(items: pd.DataFrame, ext: pd.DataFrame):
    merged = ext.merge(items[["item_id", "note_url"]], on="item_id", how="left")

    resource_rows = []
    for _, row in merged.iterrows():
        for field in ["resources", "tools", "platforms"]:
            for item in parse_list(row.get(field)):
                item = item.strip()
                if item:
                    resource_rows.append({
                        "resource": item,
                        "item_id": row["item_id"],
                        "relevance_score": row.get("relevance_score", 0),
                        "actionability_score": row.get("actionability_score", 0),
                        "note_url": row.get("note_url", ""),
                        "evidence": row.get("evidence_sentence", ""),
                    })

    if not resource_rows:
        print("resource_summary.csv  0 条（无资源数据）")
        return

    rf = pd.DataFrame(resource_rows)
    summary = (
        rf.groupby("resource")
        .agg(
            出现次数=("item_id", "count"),
            平均relevance=("relevance_score", "mean"),
            平均actionability=("actionability_score", "mean"),
            代表性证据=("evidence", "first"),
            note_url=("note_url", "first"),
        )
        .reset_index()
        .sort_values("出现次数", ascending=False)
    )
    summary["平均relevance"] = summary["平均relevance"].round(1)
    summary["平均actionability"] = summary["平均actionability"].round(1)

    path = OUTPUTS / "resource_summary.csv"
    summary.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"resource_summary.csv  {len(summary)} 种资源  → {path}")


# ── 3. pain_point_summary ─────────────────────────────────────────────────────
def report_pain_points(items: pd.DataFrame, ext: pd.DataFrame):
    merged = ext.merge(
        items[["item_id", "source_type", "parent_note_title", "text", "note_url"]],
        on="item_id", how="left"
    )

    rows = []
    for _, row in merged.iterrows():
        for pain in parse_list(row.get("pain_points")):
            pain = pain.strip()
            if pain:
                rows.append({
                    "pain_point": pain,
                    "item_id": row["item_id"],
                    "source_type": row.get("source_type", ""),
                    "代表性原文": str(row.get("evidence_sentence") or row.get("text", ""))[:100],
                    "对应用户需求": str(parse_list(row.get("user_needs"))[:1])[2:-2] if parse_list(row.get("user_needs")) else "",
                    "可转化功能": str(parse_list(row.get("agent_opportunities"))[:1])[2:-2] if parse_list(row.get("agent_opportunities")) else "",
                    "note_url": row.get("note_url", ""),
                })

    if not rows:
        print("pain_point_summary.csv  0 条")
        return

    pf = pd.DataFrame(rows)
    summary = (
        pf.groupby("pain_point")
        .agg(
            出现次数=("item_id", "count"),
            代表性原文=("代表性原文", "first"),
            对应用户需求=("对应用户需求", "first"),
            可转化功能=("可转化功能", "first"),
            note_url=("note_url", "first"),
        )
        .reset_index()
        .sort_values("出现次数", ascending=False)
    )

    path = OUTPUTS / "pain_point_summary.csv"
    summary.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"pain_point_summary.csv  {len(summary)} 个痛点  → {path}")


# ── 4. agent_opportunity_summary ──────────────────────────────────────────────
def report_opportunities(items: pd.DataFrame, ext: pd.DataFrame):
    merged = ext.merge(
        items[["item_id", "note_url", "like_count"]],
        on="item_id", how="left"
    )

    rows = []
    for _, row in merged.iterrows():
        for opp in parse_list(row.get("agent_opportunities")):
            opp = opp.strip()
            if opp:
                pains = parse_list(row.get("pain_points"))
                rows.append({
                    "机会点": opp,
                    "item_id": row["item_id"],
                    "对应痛点": "；".join(pains[:2]) if pains else "",
                    "用户原话证据": str(row.get("evidence_sentence", ""))[:100],
                    "actionability_score": row.get("actionability_score", 0),
                    "relevance_score": row.get("relevance_score", 0),
                    "note_url": row.get("note_url", ""),
                })

    if not rows:
        print("agent_opportunity_summary.csv  0 条")
        return

    of = pd.DataFrame(rows)
    summary = (
        of.groupby("机会点")
        .agg(
            出现次数=("item_id", "count"),
            对应痛点=("对应痛点", "first"),
            用户原话证据=("用户原话证据", "first"),
            平均actionability=("actionability_score", "mean"),
            平均relevance=("relevance_score", "mean"),
            note_url=("note_url", "first"),
        )
        .reset_index()
        .sort_values(["出现次数", "平均actionability"], ascending=False)
    )
    summary["平均actionability"] = summary["平均actionability"].round(1)
    summary["平均relevance"] = summary["平均relevance"].round(1)

    # 简单优先级打分
    def priority(row):
        if row["出现次数"] >= 3 and row["平均actionability"] >= 4:
            return "高"
        elif row["出现次数"] >= 2 or row["平均actionability"] >= 3:
            return "中"
        return "低"

    summary["优先级"] = summary.apply(priority, axis=1)

    path = OUTPUTS / "agent_opportunity_summary.csv"
    summary.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"agent_opportunity_summary.csv  {len(summary)} 个机会  → {path}")


def main():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    items, ext = load(con)
    con.close()

    print(f"数据：{len(items)} items，{len(ext)} extractions\n")

    report_high_value(items, ext)
    report_resources(items, ext)
    report_pain_points(items, ext)
    report_opportunities(items, ext)

    print(f"\n全部报告已保存到 {OUTPUTS}")


if __name__ == "__main__":
    main()
