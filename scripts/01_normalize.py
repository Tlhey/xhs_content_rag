"""数据标准化：post + comment → 统一 items.parquet，去除隐私字段。"""
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
PROCESSED.mkdir(parents=True, exist_ok=True)

PRIVACY_FIELDS = {"user_id", "nickname", "avatar", "xsec_token"}


def parse_count(x) -> int:
    if x is None or x == "":
        return 0
    s = str(x).strip()
    if "万" in s:
        return int(float(s.replace("万", "")) * 10000)
    try:
        return int(float(s))
    except ValueError:
        return 0


def ts_to_str(ts) -> str | None:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts) / 1000).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def load(filename):
    with open(RAW / filename, encoding="utf-8") as f:
        return json.load(f)


def normalize_posts(posts: list) -> pd.DataFrame:
    rows = []
    for p in posts:
        tags = [t.get("name", "") for t in p.get("tag_list", []) if isinstance(t, dict)]
        rows.append({
            "item_id": f"post:{p['note_id']}",
            "source_type": "post",
            "note_id": p["note_id"],
            "comment_id": None,
            "title": str(p.get("title", "")).strip(),
            "text": (str(p.get("title", "")) + " " + str(p.get("desc", ""))).strip(),
            "raw_text": str(p.get("desc", "")).strip(),
            "source_keyword": p.get("source_keyword", ""),
            "tag_list": ",".join(tags),
            "like_count": parse_count(p.get("liked_count")),
            "collect_count": parse_count(p.get("collected_count")),
            "comment_count": parse_count(p.get("comment_count")),
            "share_count": parse_count(p.get("share_count")),
            "note_url": p.get("note_url", ""),
            "created_at": ts_to_str(p.get("time")),
            "parent_note_title": None,
            "parent_note_desc": None,
        })
    return pd.DataFrame(rows)


def normalize_comments(comments: list, post_df: pd.DataFrame) -> pd.DataFrame:
    # 去重 post，每个 note_id 保留一条
    post_lookup = post_df.drop_duplicates("note_id").set_index("note_id")

    rows = []
    for c in comments:
        note_id = c.get("note_id", "")
        parent = post_lookup.loc[note_id] if note_id in post_lookup.index else None
        rows.append({
            "item_id": f"comment:{c['comment_id']}",
            "source_type": "comment",
            "note_id": note_id,
            "comment_id": c["comment_id"],
            "title": None,
            "text": str(c.get("content", "")).strip(),
            "raw_text": str(c.get("content", "")).strip(),
            "source_keyword": parent["source_keyword"] if parent is not None else "",
            "tag_list": "",
            "like_count": parse_count(c.get("like_count")),
            "collect_count": 0,
            "comment_count": parse_count(c.get("sub_comment_count", 0)),
            "share_count": 0,
            "note_url": parent["note_url"] if parent is not None else "",
            "created_at": ts_to_str(c.get("create_time")),
            "parent_note_title": parent["title"] if parent is not None else None,
            "parent_note_desc": parent["raw_text"] if parent is not None else None,
        })
    return pd.DataFrame(rows)


def main():
    posts_raw = load("search_contents_2026-05-26.json")
    comments_raw = load("search_comments_2026-05-26.json")

    post_df = normalize_posts(posts_raw)
    comment_df = normalize_comments(comments_raw, post_df)

    # 去重 post（同一 note_id 可能因不同 source_keyword 重复抓取）
    post_df_dedup = post_df.drop_duplicates("note_id").reset_index(drop=True)

    items_df = pd.concat([post_df_dedup, comment_df], ignore_index=True)

    post_df.to_parquet(PROCESSED / "posts.parquet", index=False)
    comment_df.to_parquet(PROCESSED / "comments.parquet", index=False)
    items_df.to_parquet(PROCESSED / "items.parquet", index=False)

    print(f"posts.parquet:    {len(post_df)} rows  (dedup: {len(post_df_dedup)})")
    print(f"comments.parquet: {len(comment_df)} rows")
    print(f"items.parquet:    {len(items_df)} rows total")
    print(f"saved to {PROCESSED}")


if __name__ == "__main__":
    main()
