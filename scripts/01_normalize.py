"""数据标准化（增量模式）。

扫描 data/raw/ 下所有 search_contents_*.json 和 search_comments_*.json，
只把 item_id 不在 items.parquet 中的新条目追加进去。

用法：
    python scripts/01_normalize.py          # 增量追加新数据
    python scripts/01_normalize.py --full   # 忽略已有数据，从头全量重建
"""
import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
PROCESSED.mkdir(parents=True, exist_ok=True)


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


def load_json(path: Path) -> list:
    with open(path, encoding="utf-8") as f:
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


def normalize_comments(comments: list, post_lookup: dict) -> pd.DataFrame:
    rows = []
    for c in comments:
        note_id = c.get("note_id", "")
        parent = post_lookup.get(note_id)
        rows.append({
            "item_id": f"comment:{c['comment_id']}",
            "source_type": "comment",
            "note_id": note_id,
            "comment_id": c["comment_id"],
            "title": None,
            "text": str(c.get("content", "")).strip(),
            "raw_text": str(c.get("content", "")).strip(),
            "source_keyword": parent["source_keyword"] if parent else "",
            "tag_list": "",
            "like_count": parse_count(c.get("like_count")),
            "collect_count": 0,
            "comment_count": parse_count(c.get("sub_comment_count", 0)),
            "share_count": 0,
            "note_url": parent["note_url"] if parent else "",
            "created_at": ts_to_str(c.get("create_time")),
            "parent_note_title": parent["title"] if parent else None,
            "parent_note_desc": parent["raw_text"] if parent else None,
        })
    return pd.DataFrame(rows)


def build_post_lookup(post_df: pd.DataFrame) -> dict:
    """note_id → post row dict，每个 note_id 保留一条。"""
    return (
        post_df.drop_duplicates("note_id")
               .set_index("note_id")
               .to_dict("index")
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="全量重建，忽略已有数据")
    args = parser.parse_args()

    # 加载已有 items（增量模式用）
    existing_ids: set = set()
    items_path = PROCESSED / "items.parquet"
    if not args.full and items_path.exists():
        existing_ids = set(pd.read_parquet(items_path, columns=["item_id"])["item_id"])
        print(f"existing items: {len(existing_ids)}")

    # 扫描所有 raw 文件
    content_files = sorted(RAW.glob("search_contents_*.json"))
    comment_files = sorted(RAW.glob("search_comments_*.json"))
    print(f"raw files: {len(content_files)} content, {len(comment_files)} comment")

    # 读取并合并所有 posts，按 note_id 去重
    all_posts: list[dict] = []
    for f in content_files:
        all_posts.extend(load_json(f))
    post_df_all = normalize_posts(all_posts).drop_duplicates("note_id")
    post_lookup = build_post_lookup(post_df_all)

    # 读取并合并所有 comments
    all_comments: list[dict] = []
    for f in comment_files:
        all_comments.extend(load_json(f))
    comment_df_all = normalize_comments(all_comments, post_lookup)
    comment_df_all = comment_df_all.drop_duplicates("item_id")

    # 合并 items
    items_all = pd.concat([post_df_all, comment_df_all], ignore_index=True)

    # 只保留新 item_id
    new_items = items_all[~items_all["item_id"].isin(existing_ids)]
    print(f"new items to add: {len(new_items)}")

    if len(new_items) == 0:
        print("no new data, nothing to do.")
        return

    # 追加到已有 parquet（或新建）
    if not args.full and items_path.exists():
        existing_df = pd.read_parquet(items_path)
        merged = pd.concat([existing_df, new_items], ignore_index=True)
    else:
        merged = items_all

    merged.to_parquet(items_path, index=False)

    # 同时更新 posts.parquet / comments.parquet（全量覆盖，方便查看）
    post_df_all.to_parquet(PROCESSED / "posts.parquet", index=False)
    comment_df_all.to_parquet(PROCESSED / "comments.parquet", index=False)

    print(f"items.parquet: {len(merged)} rows total  (+{len(new_items)} new)")


if __name__ == "__main__":
    main()
