"""LLM 批量抽取：对 should_send_to_llm=True 的 item 做结构化抽取。

用法：
    python scripts/03_llm_extract.py            # 处理全部待抽取 item
    python scripts/03_llm_extract.py --limit 20 # 只处理前 20 条（测试用）
    python scripts/03_llm_extract.py --retry     # 只重跑上次 parse_failed 的
"""
import argparse
import json
import os
import time
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

client = OpenAI(
    api_key=os.environ["MINIMAX_API_KEY"],
    base_url=os.environ["MINIMAX_BASE_URL"],
)
MODEL = os.environ.get("MINIMAX_MODEL", "MiniMax-M2.7")
SYSTEM_PROMPT = PROMPT_FILE.read_text(encoding="utf-8")


def build_user_message(row: dict) -> str:
    parts = []
    if row.get("source_type") == "comment":
        if row.get("parent_note_title"):
            parts.append(f"【所属帖子标题】{row['parent_note_title']}")
        if row.get("parent_note_desc"):
            desc = str(row["parent_note_desc"])[:300]
            parts.append(f"【所属帖子简介】{desc}")
    if row.get("title"):
        parts.append(f"【标题】{row['title']}")
    parts.append(f"【正文】{row['text']}")
    if row.get("tag_list"):
        parts.append(f"【标签】{row['tag_list']}")
    if row.get("source_keyword"):
        parts.append(f"【来源关键词】{row['source_keyword']}")
    parts.append(f"【点赞数】{row.get('like_count', 0)}")
    return "\n".join(parts)


import re as _re


def _strip_response(raw: str) -> str:
    """去掉 <think>...</think> 推理块和 markdown 代码块，只留 JSON。"""
    raw = _re.sub(r"<think>.*?</think>", "", raw, flags=_re.DOTALL).strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return raw


def call_llm(user_msg: str, retries: int = 2) -> tuple[dict | None, bool]:
    """返回 (parsed_dict, parse_failed)"""
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
            raw = resp.choices[0].message.content.strip()
            raw = _strip_response(raw)
            result = json.loads(raw)
            return result, False
        except json.JSONDecodeError:
            if attempt < retries - 1:
                time.sleep(1)
        except Exception as e:
            print(f"  API error: {e}")
            time.sleep(2)
    return None, True


def load_done_ids() -> set:
    done = set()
    if OUT_JSONL.exists():
        with open(OUT_JSONL, encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    done.add(obj["item_id"])
                except Exception:
                    pass
    return done


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--retry", action="store_true", help="只重跑 parse_failed")
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

    print(f"already done: {len(done_ids)}  |  to process: {len(to_process)}")

    PROCESSED.mkdir(parents=True, exist_ok=True)
    success = failed = 0

    with open(OUT_JSONL, "a", encoding="utf-8") as out:
        for _, row in tqdm(to_process.iterrows(), total=len(to_process)):
            user_msg = build_user_message(row.to_dict())
            result, parse_failed = call_llm(user_msg)

            record = {"item_id": row["item_id"], "parse_failed": parse_failed}
            if result:
                record.update(result)
                success += 1
            else:
                failed += 1

            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()

    print(f"\ndone. success={success} failed={failed}")
    print(f"output → {OUT_JSONL}")

    # 转 parquet
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
