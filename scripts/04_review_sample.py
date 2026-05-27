"""人工抽样检查：从 extracted_items 中按 relevance_score 分层抽样，输出 CSV。"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
PROCESSED = ROOT / "data" / "processed"
OUTPUTS = ROOT / "data" / "outputs"
OUTPUTS.mkdir(parents=True, exist_ok=True)


def main():
    items = pd.read_parquet(PROCESSED / "items.parquet")
    ext = pd.read_parquet(PROCESSED / "extracted_items.parquet")

    df = ext.merge(
        items[["item_id", "source_type", "parent_note_title", "text", "note_url"]],
        on="item_id",
        how="left",
    )

    COLS = [
        "item_id", "source_type", "parent_note_title", "text",
        "main_category", "relevance_score", "actionability_score",
        "summary", "resources", "pain_points", "agent_opportunities",
        "evidence_sentence", "parse_failed", "note_url",
        "human_check", "human_note",
    ]
    for c in ("human_check", "human_note"):
        if c not in df.columns:
            df[c] = ""

    samples = []

    # parse_failed 全部输出
    failed = df[df["parse_failed"] == True]
    if len(failed):
        samples.append(failed)
        print(f"parse_failed: {len(failed)}")

    df_ok = df[df["parse_failed"] != True].copy()
    df_ok["relevance_score"] = pd.to_numeric(df_ok.get("relevance_score", 0), errors="coerce").fillna(0)

    for score, n in [(5, 30), (4, 30), (3, 30)]:
        bucket = df_ok[df_ok["relevance_score"] == score]
        s = bucket.sample(min(n, len(bucket)), random_state=42)
        samples.append(s)
        print(f"relevance_score={score}: sampled {len(s)}/{len(bucket)}")

    low = df_ok[df_ok["relevance_score"] <= 2]
    s = low.sample(min(30, len(low)), random_state=42)
    samples.append(s)
    print(f"relevance_score<=2: sampled {len(s)}/{len(low)}")

    out = pd.concat(samples, ignore_index=True)

    # 保留已有的列，补齐缺失列
    final_cols = [c for c in COLS if c in out.columns]
    out = out[final_cols]

    out_path = OUTPUTS / "review_sample.csv"
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\ntotal sample: {len(out)} rows → {out_path}")
    print("请在 CSV 中填写 human_check (good/bad/unsure) 和 human_note")


if __name__ == "__main__":
    main()
