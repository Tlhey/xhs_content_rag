"""规则初筛：给每条 item 打 rule_score / rule_labels / should_send_to_llm。"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
PROCESSED = ROOT / "data" / "processed"

CAREER_KW = [
    "找工", "求职", "实习", "校招", "春招", "秋招", "面试", "面邀",
    "offer", "简历", "内推", "投递", "岗位", "JD", "转行",
    "产品经理", "AI产品", "开发实习", "Agent开发", "算法", "SDE", "MLE",
]
AGENT_KW = [
    "agent", "Agent", "大模型", "LLM", "Claude", "ChatGPT",
    "Gemini", "Dify", "coze", "扣子", "workflow", "工作流", "MCP",
    "Claude Code", "vibecoding", "项目", "demo",
]
RESOURCE_KW = [
    "平台", "网站", "渠道", "资源", "教程", "资料", "路线", "学习路线",
    "项目推荐", "接单", "兼职", "副业", "群", "上车", "怎么用",
]
PAIN_KW = [
    "不会", "不懂", "小白", "零基础", "卡住", "不知道", "求问",
    "怎么入门", "怎么做", "需要什么基础", "太难", "焦虑", "后悔",
]
NOISE_KW = [
    "老公", "男朋友", "恋爱", "穿搭", "上衣", "裙子", "鞋子",
    "好看", "纯爱", "代餐", "护肤", "美甲",
]


def hit(text: str, keywords: list[str]) -> bool:
    t = text.lower()
    return any(k.lower() in t for k in keywords)


def score_item(text: str) -> dict:
    career = hit(text, CAREER_KW)
    agent = hit(text, AGENT_KW)
    resource = hit(text, RESOURCE_KW)
    pain = hit(text, PAIN_KW)
    noise = hit(text, NOISE_KW)
    too_short = len([c for c in text if "一" <= c <= "鿿"]) < 6

    labels = []
    score = 0

    if career:
        labels.append("career")
        score += 2
    if agent:
        labels.append("agent")
        score += 2
    if resource:
        labels.append("resource")
        score += 1
    if pain:
        labels.append("pain_point")
        score += 1
    if noise and not (career or agent or resource):
        labels.append("noise")
        score -= 2
    if too_short:
        labels.append("too_short")
        score -= 1

    # 组合加分
    if career and agent:
        score += 1
    if agent and resource:
        score += 1

    send = score >= 2 and not too_short

    return {
        "rule_score": score,
        "rule_labels": ",".join(labels),
        "should_send_to_llm": send,
    }


def main():
    df = pd.read_parquet(PROCESSED / "items.parquet")

    results = df["text"].fillna("").apply(score_item).apply(pd.Series)
    df = pd.concat([df, results], axis=1)

    df.to_parquet(PROCESSED / "items.parquet", index=False)

    total = len(df)
    send = df["should_send_to_llm"].sum()
    print(f"total items:        {total}")
    print(f"should_send_to_llm: {send}  ({send/total*100:.1f}%)")
    print()
    print("rule_labels distribution (top 10):")
    from collections import Counter
    label_counter: Counter = Counter()
    for row in df["rule_labels"]:
        for lbl in str(row).split(","):
            if lbl:
                label_counter[lbl] += 1
    for lbl, cnt in label_counter.most_common(10):
        print(f"  {lbl:20s}  {cnt}")


if __name__ == "__main__":
    main()
