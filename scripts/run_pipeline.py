"""Pipeline 管理器：同步新 rawdata → 增量处理 → 生成带日期的 outputs。

用法：
    python scripts/run_pipeline.py                    # 自动同步 + 增量跑
    python scripts/run_pipeline.py --sync-only        # 只同步文件，不跑 pipeline
    python scripts/run_pipeline.py --no-llm           # 跳过 LLM 抽取（快速模式）
    python scripts/run_pipeline.py --full-rebuild     # 全量重建（清空重跑）
"""
import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
RAW = ROOT / "data" / "raw"
OUTPUTS = ROOT / "data" / "outputs"
CRAWLER_DATA = ROOT / "MediaCrawler" / "data" / "xhs" / "json"
PYTHON = sys.executable


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def run(script: str, *args):
    cmd = [PYTHON, str(ROOT / "scripts" / script)] + list(args)
    log(f"running: {script} {' '.join(args)}")
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        log(f"ERROR: {script} failed (exit {result.returncode})")
        sys.exit(result.returncode)


# ── Step 1: 同步新文件到 data/raw/ ────────────────────────────────────────────
def sync_raw() -> list[str]:
    """把 MediaCrawler/data/xhs/json/ 里的新文件复制到 data/raw/，返回新增文件列表。"""
    RAW.mkdir(parents=True, exist_ok=True)
    added = []
    for src in sorted(CRAWLER_DATA.glob("search_*.json")):
        dst = RAW / src.name
        if not dst.exists():
            shutil.copy2(src, dst)
            log(f"  synced: {src.name}")
            added.append(src.name)
        else:
            log(f"  skip (exists): {src.name}")
    return added


# ── Step 2: 生成带日期的 output 目录 ──────────────────────────────────────────
def make_output_dir() -> Path:
    date_tag = datetime.now().strftime("%Y-%m-%d")
    out_dir = OUTPUTS / date_tag
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def copy_outputs_to_dated_dir(out_dir: Path):
    for csv in OUTPUTS.glob("*.csv"):
        dst = out_dir / csv.name
        shutil.copy2(csv, dst)
        log(f"  saved → {dst.relative_to(ROOT)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sync-only", action="store_true")
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--full-rebuild", action="store_true")
    args = parser.parse_args()

    print("=" * 55)
    log("Pipeline 启动")
    print("=" * 55)

    # 1. 同步 rawdata
    log("Step 0: 同步 rawdata")
    added = sync_raw()
    if not added:
        log("没有新文件，检查 items.parquet 是否有未处理条目...")
        # 检查是否有未打分或未抽取的条目
        import pandas as pd
        items_path = ROOT / "data" / "processed" / "items.parquet"
        ext_path = ROOT / "data" / "processed" / "extracted_items.jsonl"
        has_unscored = False
        has_unextracted = False
        if items_path.exists():
            df = pd.read_parquet(items_path)
            has_unscored = "rule_score" not in df.columns or df["rule_score"].isna().any()
            if "should_send_to_llm" in df.columns:
                need_llm = set(df[df["should_send_to_llm"] == True]["item_id"])
                done_ids = set()
                if ext_path.exists():
                    import json
                    for line in open(ext_path):
                        try: done_ids.add(json.loads(line)["item_id"])
                        except: pass
                has_unextracted = bool(need_llm - done_ids)
        if not args.full_rebuild and not has_unscored and not has_unextracted:
            log("无新数据也无未处理条目，退出（用 --full-rebuild 强制重跑）")
            return
        log(f"检测到未处理条目（unscored={has_unscored}, unextracted={has_unextracted}），继续...")
    else:
        log(f"新增 {len(added)} 个文件：{added}")

    if args.sync_only:
        log("--sync-only 模式，同步完成，退出")
        return

    # 2. 标准化（增量）
    log("Step 1: 标准化")
    normalize_args = ["--full"] if args.full_rebuild else []
    run("01_normalize.py", *normalize_args)

    # 3. 规则初筛
    log("Step 2: 规则初筛")
    run("02_rule_filter.py")

    # 4. LLM 抽取
    if not args.no_llm:
        log("Step 3: LLM 抽取（增量，只处理新条目）")
        run("03_llm_extract.py", "--workers", "3")
    else:
        log("Step 3: 跳过 LLM 抽取（--no-llm）")

    # 5. 写入 DuckDB
    log("Step 4: 写入 DuckDB")
    db_args = ["--full"] if args.full_rebuild else []
    run("05_build_db.py", *db_args)

    # 6. 生成报告
    log("Step 5: 生成报告")
    run("07_generate_report.py")

    # 7. 把 outputs 复制一份到带日期的子目录
    out_dir = make_output_dir()
    log(f"Step 6: 归档 outputs → {out_dir.relative_to(ROOT)}")
    copy_outputs_to_dated_dir(out_dir)

    print("=" * 55)
    log(f"Pipeline 完成！报告在 data/outputs/{out_dir.name}/")
    print("=" * 55)


if __name__ == "__main__":
    main()
