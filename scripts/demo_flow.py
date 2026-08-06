from __future__ import annotations

import argparse
import json
import os
import time

import requests


BASE_URL = os.getenv("QINGSHU_BASE_URL", "http://127.0.0.1:8000")


def call(method: str, path: str, **kwargs):
    response = requests.request(method, BASE_URL + path, timeout=60, **kwargs)
    response.raise_for_status()
    return response.json()


def show(title: str, payload, compact: bool = False):
    print(f"\n## {title}")
    if compact:
        if payload.get("answer"):
            print(payload["answer"])
            return
        article = payload.get("article") or {}
        if article:
            print(article.get("title") or "文章已生成")
            print((article.get("summary") or article.get("body") or "")[:500])
            print(f"发布决策：{payload.get('decision', 'unknown')}")
            return
        if payload.get("id") and payload.get("name"):
            print(f"已创建用户：{payload['name']}（{payload['id']}）")
            return
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="运行清数智算完整 Demo 流程")
    parser.add_argument("--compact", action="store_true", help="只显示适合人工阅读的摘要")
    args = parser.parse_args()

    user = call("POST", "/users", json={"name": "命令行 Demo 用户"})
    user_id = user["id"]
    show("创建用户", user, args.compact)

    added = call(
        "POST",
        f"/users/{user_id}/chat",
        json={
            "message": "把600519加入自选，因为我想验证高端白酒需求是否企稳",
            "model_tier": "economy",
        },
    )
    show("对话添加自选股", added, args.compact)

    market = call(
        "POST",
        f"/users/{user_id}/chat",
        json={"message": "今天大盘和热门板块怎么样？", "model_tier": "economy"},
    )
    show("市场简报", market, args.compact)

    stock = call(
        "POST",
        f"/users/{user_id}/chat",
        json={
            "message": "贵州茅台现在值得继续研究什么？",
            "symbol": "600519",
            "model_tier": "deep",
        },
    )
    show("单股研究", stock, args.compact)

    article = {"decision": "waiting", "article": None}
    for _ in range(30):
        items = call("GET", "/articles", params={"limit": 1}).get("items", [])
        if items:
            article = {"decision": "background_published", "article": items[0]}
            break
        time.sleep(0.5)
    show("Market Pulse 行情文章", article, args.compact)

    candidate = call(
        "POST",
        f"/users/{user_id}/chat",
        json={"message": "记住：我更在意最大回撤，不希望只看收益率"},
    )
    show("创建记忆候选", candidate, args.compact)

    if args.compact:
        print("\n✅ 开发联调流程已跑通。产品页面可在 /demo 查看。")


if __name__ == "__main__":
    main()
