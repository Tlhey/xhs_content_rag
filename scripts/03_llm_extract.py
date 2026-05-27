"""LLM 批量抽取：对 should_send_to_llm=True 的 item 做结构化抽取。

用法：
    python scripts/03_llm_extract.py               # 全量，默认 10 并发
    python scripts/03_llm_extract.py --limit 20    # 只跑前 20 条（测试）
    python scripts/03_llm_extract.py --workers 5   # 调整并发数
    python scripts/03_llm_extract.py --retry       # 只重跑 parse_failed
"""
import argparse
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI
from tqdm import tqdm

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

PROCESSED = ROOT / "data" / "processed"
PROMPT_FILE = ROOT / "prompts" / "extract_item_v1.txt"
OUT_JSONL = PROCESSED / "extracted_items.jsonl"

MODEL = os.environ.get("MINIMAX_MODEL", "MiniMax-M2.7")
SYSTEM_PROMPT = PROMPT_FILE.read_text(encoding="utf-8")

# 每个线程独立 client，避免连接争用
_local = threading.local()


def get_client() -> OpenAI:
    if not hasattr(_local, "client"):
        _local.client = OpenAI(
            api_key=os.environ["MINIMAX_API_KEY"],
            base_url=os.environ["MINIMAX_BASE_URL"],
        )
    return _local.client


def build_user_message(row: dict) -> str:
    parts = []
    if row.get("source_type") == "comment":
        if row.get("parent_note_title"):
            parts.append(f"【所属帖子标题】{row['parent_note_title']}")
        if row.get("parent_note_desc"):
            parts.append(f"【所属帖子简介】{str(row['parent_note_desc'])[:300]}")
    if row.get("title"):
        parts.append(f"【标题】{row['title']}")
    parts.append(f"【正文】{row['text']}")
    if row.get("tag_list"):
        parts.append(f"【标签】{row['tag_list']}")
    if row.get("source_keyword"):
        parts.append(f"【来源关键词】{row['source_keyword']}")
    parts.append(f"【点赞数】{row.get('like_count', 0)}")
    return "\n".join(parts)


def _strip_response(raw: str) -> str:
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return raw


def call_llm(user_msg: str, retries: int = 4) -> tuple[dict | None, bool]:
    client = get_client()
    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.1,
                max_tokens=800,
            )
            raw = _strip_response(resp.choices[0].message.content.strip())
            return json.loads(raw), False
        except json.JSONDecodeError:
            if attempt < retries - 1:
                time.sleep(2)
        except Exception as e:
            err = str(e)
            if "429" in err or "rate_limit" in err:
                wait = 10 * (2 ** attempt)  # 10s, 20s, 40s, 80s
                print(f"\n  rate limit, wait {wait}s...")
                time.sleep(wait)
            else:
                print(f"\n  API error: {e}")
                time.sleep(3)
    return None, True


def process_row(row: dict) -> dict:
    user_msg = build_user_message(row)
    result, parse_failed = call_llm(user_msg)
    record = {"item_id": row["item_id"], "parse_failed": parse_failed}
    if result:
        record.update(result)
    return record


def load_done_ids() -> set:
    done = set()
    if OUT_JSONL.exists():
        with open(OUT_JSONL, encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(json.loads(line)["item_id"])
                except Exception:
                    pass
    return done


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--retry", action="store_true")
    args = parser.parse_args()

    df = pd.read_parquet(PROCESSED / "items.parquet")
    to_process = df[df["should_send_to_llm"] == True].copy()
    done_ids = load_done_ids()

    if args.retry:
        failed_ids = set()
        if OUT_JSONL.exists():
            with open(OUT_JSONL, encoding="utf-8") as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                        if obj.get("parse_failed"):
                            failed_ids.add(obj["item_id"])
                    except Exception:
                        pass
        to_process = to_process[to_process["item_id"].isin(failed_ids)]
        done_ids -= failed_ids
        print(f"retry mode: {len(to_process)} failed items")
    else:
        to_process = to_process[~to_process["item_id"].isin(done_ids)]

    if args.limit:
        to_process = to_process.head(args.limit)

    print(f"already done: {len(done_ids)}  |  to process: {len(to_process)}  |  workers: {args.workers}")

    PROCESSED.mkdir(parents=True, exist_ok=True)
    write_lock = threading.Lock()
    success = failed = 0
    counter_lock = threading.Lock()

    rows = to_process.to_dict("records")

    with open(OUT_JSONL, "a", encoding="utf-8") as out:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(process_row, row): row["item_id"] for row in rows}
            with tqdm(total=len(futures)) as bar:
                for fut in as_completed(futures):
                    record = fut.result()
                    with write_lock:
                        out.write(json.dumps(record, ensure_ascii=False) + "\n")
                        out.flush()
                    with counter_lock:
                        if record.get("parse_failed"):
                            failed += 1
                        else:
                            success += 1
                    bar.update(1)
                    bar.set_postfix(ok=success, fail=failed)

    print(f"\ndone. success={success}  failed={failed}")

    records = []
    with open(OUT_JSONL, encoding="utf-8") as f:
        for line in f:
            try:
                records.append(json.loads(line))
            except Exception:
                pass
    if records:
        pd.DataFrame(records).to_parquet(PROCESSED / "extracted_items.parquet", index=False)
        print(f"saved extracted_items.parquet ({len(records)} rows)")


if __name__ == "__main__":
    main()
