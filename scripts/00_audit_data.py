"""数据审计：确认字段完整性、重复情况、note_id 交集。"""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent.parent
RAW = ROOT / "data" / "raw"


def load(filename):
    with open(RAW / filename, encoding="utf-8") as f:
        return json.load(f)


def main():
    posts = load("search_contents_2026-05-26.json")
    comments = load("search_comments_2026-05-26.json")

    post_ids = [p["note_id"] for p in posts]
    comment_note_ids = [c["note_id"] for c in comments]

    unique_post_ids = set(post_ids)
    unique_comment_note_ids = set(comment_note_ids)
    intersection = unique_post_ids & unique_comment_note_ids

    dup_posts = len(post_ids) - len(unique_post_ids)
    empty_title = sum(1 for p in posts if not str(p.get("title", "")).strip())
    empty_desc = sum(1 for p in posts if not str(p.get("desc", "")).strip())
    empty_comment = sum(1 for c in comments if not str(c.get("content", "")).strip())

    kw_counter = Counter(p.get("source_keyword", "") for p in posts)

    print("=" * 50)
    print(f"posts rows:              {len(posts)}")
    print(f"comments rows:           {len(comments)}")
    print(f"unique post note_id:     {len(unique_post_ids)}")
    print(f"unique comment note_id:  {len(unique_comment_note_ids)}")
    print(f"note_id intersection:    {len(intersection)}")
    print(f"duplicate posts:         {dup_posts}")
    print(f"empty title:             {empty_title}")
    print(f"empty desc:              {empty_desc}")
    print(f"empty comment content:   {empty_comment}")
    print()
    print("source_keyword distribution:")
    for kw, cnt in kw_counter.most_common():
        print(f"  {kw!r:20s}  {cnt}")
    print("=" * 50)

    # 找出有评论但无 post 的 note_id
    orphan = unique_comment_note_ids - unique_post_ids
    if orphan:
        print(f"\n评论中有 {len(orphan)} 个 note_id 在 posts 里找不到对应帖子")


if __name__ == "__main__":
    main()
