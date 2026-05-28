"""人工审核界面：按帖子分组，一次看一个帖子和它的所有评论。

运行：
    streamlit run app/review.py
"""
import json
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).parent.parent
CSV_PATH = ROOT / "data" / "outputs" / "review_sample.csv"

CATEGORIES = [
    ("",          "⬜ 未分类"),
    ("project",   "🔧 可借鉴项目"),
    ("interview", "💼 Agent 岗位面试"),
    ("learning",  "📚 学习进度 / 分享"),
    ("job_post",  "📋 可投递岗位"),
    ("tbd",       "🕐 待补充"),
    ("other",     "💬 其他"),
]
CAT_KEYS   = [c[0] for c in CATEGORIES]
CAT_LABELS = [c[1] for c in CATEGORIES]
KEY_TO_LABEL = dict(CATEGORIES)
LABEL_TO_KEY = {v: k for k, v in CATEGORIES}

st.set_page_config(page_title="XHS Review", layout="wide")


@st.cache_data
def load_df():
    df = pd.read_csv(CSV_PATH)
    for col in ["human_check", "human_note"]:
        if col not in df.columns:
            df[col] = ""
    df["human_check"] = df["human_check"].fillna("")
    df["human_note"]  = df["human_note"].fillna("")
    # 去重：同一 item_id 保留已有 human_check 的那条，否则保留第一条
    df["_has_check"] = df["human_check"] != ""
    df = df.sort_values("_has_check", ascending=False).drop_duplicates("item_id").drop(columns="_has_check")
    df = df.reset_index(drop=True)
    return df


def save_df(df: pd.DataFrame):
    df.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
    st.cache_data.clear()


def get_note_id(row) -> str:
    """从 item_id 或 parent_note_title 推断 note_id 用于分组。"""
    iid = str(row.get("item_id", ""))
    if iid.startswith("post:"):
        return iid[5:]
    # comment 的 note_id 要从 items.parquet 里拿，这里用 parent_note_title 做代理分组
    return str(row.get("parent_note_title", "")) or iid


if "df"     not in st.session_state: st.session_state.df     = load_df()
if "grp"    not in st.session_state: st.session_state.grp    = 0
if "filter" not in st.session_state: st.session_state.filter = "全部"

df = st.session_state.df

# 建分组：以 note_id 为 key，把 post 排前面
# 先从 items.parquet 补 note_id
try:
    items = pd.read_parquet(ROOT / "data" / "processed" / "items.parquet",
                            columns=["item_id", "note_id"])
    df = df.merge(items.rename(columns={"note_id": "_note_id"}), on="item_id", how="left")
    df["_group_key"] = df["_note_id"].fillna(df["item_id"])
except Exception:
    df["_group_key"] = df["item_id"].apply(
        lambda x: x[5:] if str(x).startswith("post:") else str(x)
    )

# 分组列表（保持稳定顺序）
all_groups = list(dict.fromkeys(df["_group_key"].tolist()))

# ── 侧边栏 ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("XHS Review")

    filter_opts = ["全部", "有未分类"]
    filter_opt  = st.radio("显示范围", filter_opts,
                           index=filter_opts.index(st.session_state.filter)
                           if st.session_state.filter in filter_opts else 0)
    st.session_state.filter = filter_opt

    if filter_opt == "有未分类":
        unclassified_groups = set(
            df[df["human_check"] == ""]["_group_key"].tolist()
        )
        view_groups = [g for g in all_groups if g in unclassified_groups]
    else:
        view_groups = all_groups

    total_groups = len(view_groups)
    done_items   = (df["human_check"] != "").sum()
    total_items  = len(df)

    st.metric("已分类 / 总条目", f"{done_items} / {total_items}")
    st.progress(done_items / total_items if total_items else 0)

    st.divider()
    st.write("**分类统计**")
    counts = df["human_check"].value_counts()
    for key, label in CATEGORIES:
        n = counts.get(key, 0)
        if n or key == "":
            st.write(f"{'未分类' if key == '' else label}: **{n}**")

    st.divider()
    if st.button("💾 保存到 CSV"):
        save_df(st.session_state.df)
        st.success("已保存！")

# ── 翻页 ──────────────────────────────────────────────────────────────────────
if total_groups == 0:
    st.info("没有符合条件的帖子。")
    st.stop()

if st.session_state.grp >= total_groups:
    st.session_state.grp = 0

grp_idx  = st.session_state.grp
note_key = view_groups[grp_idx]
group_df = df[df["_group_key"] == note_key].copy()
# post 排最前，comment 按 item_id 排
group_df["_sort"] = group_df["item_id"].apply(lambda x: 0 if str(x).startswith("post:") else 1)
group_df = group_df.sort_values("_sort").reset_index(drop=True)

c1, c2, c3 = st.columns([1, 4, 1])
with c1:
    if st.button("← 上一帖", use_container_width=True):
        st.session_state.grp = (grp_idx - 1) % total_groups
        st.rerun()
with c2:
    unclassified_in_group = (group_df["human_check"] == "").sum()
    status = f"⬜ {unclassified_in_group} 条未分类" if unclassified_in_group else "✅ 全部已分类"
    st.markdown(
        f"<div style='text-align:center;padding-top:6px;color:gray'>"
        f"帖子 {grp_idx+1} / {total_groups} &nbsp;·&nbsp; {status}</div>",
        unsafe_allow_html=True,
    )
with c3:
    if st.button("下一帖 →", use_container_width=True):
        st.session_state.grp = (grp_idx + 1) % total_groups
        st.rerun()

st.divider()

# ── 渲染每一条（post 在前，comments 在后）────────────────────────────────────
any_changed = False
new_values  = {}

for loop_i, (i, row) in enumerate(group_df.iterrows()):
    orig_idx = st.session_state.df[st.session_state.df["item_id"] == row["item_id"]].index
    if len(orig_idx) == 0:
        continue
    orig_idx = orig_idx[0]

    is_post = str(row.get("item_id", "")).startswith("post:")

    if is_post:
        st.markdown("### 📄 帖子")
    else:
        st.markdown("---")
        st.markdown("##### 💬 评论")

    left, right = st.columns([3, 2])

    with left:
        rel = row.get("relevance_score", "?")
        cat = row.get("main_category", "?")
        st.caption(f"LLM分类: `{cat}`  相关度: `{rel}`")

        text = str(row.get("text", "")).strip()
        height = "320px" if is_post else "160px"
        st.markdown(
            f"<div style='background:#f8f8f8;border-radius:8px;padding:10px 14px;"
            f"font-size:13px;line-height:1.7;max-height:{height};overflow-y:auto'>{text}</div>",
            unsafe_allow_html=True,
        )

        if is_post:
            if pd.notna(row.get("summary")) and str(row.get("summary")).strip():
                st.info(str(row["summary"]), icon="🤖")
        else:
            if pd.notna(row.get("evidence_sentence")) and str(row.get("evidence_sentence")).strip():
                st.success(f'「{row["evidence_sentence"]}」')

        if pd.notna(row.get("note_url")) and str(row.get("note_url")).strip():
            st.markdown(f"[🔗 原帖]({row['note_url']})")

    with right:
        current_key   = str(st.session_state.df.at[orig_idx, "human_check"]).strip()
        current_label = KEY_TO_LABEL.get(current_key, CAT_LABELS[0])
        cur_idx       = CAT_LABELS.index(current_label) if current_label in CAT_LABELS else 0

        uniq = f"{grp_idx}_{loop_i}"
        chosen_label = st.radio(
            "分类",
            options=CAT_LABELS,
            index=cur_idx,
            key=f"cat_{uniq}",
            label_visibility="collapsed",
        )
        chosen_key = LABEL_TO_KEY[chosen_label]

        current_note = str(st.session_state.df.at[orig_idx, "human_note"])
        current_note = "" if current_note == "nan" else current_note
        new_note = st.text_area(
            "备注",
            value=current_note,
            height=80,
            key=f"note_{uniq}",
            label_visibility="collapsed",
            placeholder="备注（可选）",
        )

        new_values[orig_idx] = (chosen_key, new_note)

st.divider()

# ── 底部保存按钮 ──────────────────────────────────────────────────────────────
col_save, col_next = st.columns(2)
with col_save:
    if st.button("💾 保存本帖", use_container_width=True):
        for oi, (ck, cn) in new_values.items():
            st.session_state.df.at[oi, "human_check"] = ck
            st.session_state.df.at[oi, "human_note"]  = cn
        save_df(st.session_state.df)
        st.success("已保存！")
        st.rerun()
with col_next:
    if st.button("✅ 保存并下一帖", type="primary", use_container_width=True):
        for oi, (ck, cn) in new_values.items():
            st.session_state.df.at[oi, "human_check"] = ck
            st.session_state.df.at[oi, "human_note"]  = cn
        save_df(st.session_state.df)
        st.session_state.grp = (grp_idx + 1) % total_groups
        st.rerun()
