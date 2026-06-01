"""rss_plugin Tool：查询 RSS 源。

该 Tool 面向 LLM Tool Calling：
- 主动抓取并阅读最新新闻
- 查询已订阅的 RSS 源列表
- 搜索特定关键词的文章
- 获取 RSS 源统计信息
"""

from __future__ import annotations

import asyncio
from typing import Annotated, cast

from src.app.plugin_system.api.service_api import get_service
from src.core.components.base.tool import BaseTool
from src.kernel.logger import get_logger

from .service import RSSFeedService

logger = get_logger("rss_plugin")


class RSSQueryTool(BaseTool):
    """RSS 源查询工具。"""

    tool_name: str = "query_rss"
    tool_description: str = (
        "RSS 新闻工具。查新闻请用 read_news（会实时抓取最新内容），"
        "search 仅搜索已缓存的旧文章。"
    )

    async def execute(
        self,
        action: Annotated[
            str,
            "操作类型："
            "'read_news'（实时抓取最新新闻并返回摘要，查新闻必用此操作）、"
            "'list_feeds'（列出订阅源）、"
            "'search'（仅搜索已缓存的旧文章，不会抓取新内容）、"
            "'latest'（获取本地最新文章）、"
            "'detail'（查看某篇文章的完整摘要，需提供文章编号或标题关键词）、"
            "'stats'（获取统计信息）、'categories'（查看新闻分类及对应源）",
        ],
        keyword: Annotated[
            str | None,
            "关键词。read_news 时用于匹配分类源+过滤；search 时用于搜索缓存",
        ] = None,
        limit: Annotated[
            int,
            "返回结果数量上限，默认 5",
        ] = 5,
    ) -> tuple[bool, str | dict]:
        """执行 RSS 查询。"""
        service = get_service("rss_plugin:service:rss_feed")
        if service is None:
            return False, "rss_plugin service 未加载"

        service = cast(RSSFeedService, service)

        if action == "read_news":
            topic_note = ""
            new_articles = []

            # 如果指定了关键词，先尝试匹配分类源
            if keyword:
                category_urls = service.match_category(keyword)
                if category_urls:
                    logger.info(f"read_news: 匹配到分类源 {len(category_urls)} 个，开始抓取...")
                    try:
                        new_articles = await asyncio.wait_for(
                            service.fetch_by_urls(category_urls), timeout=60.0
                        )
                    except (asyncio.TimeoutError, Exception) as e:
                        logger.warning(f"read_news: 分类源抓取失败: {type(e).__name__}: {e}")
                    topic_note = f"📡 已选择「{keyword}」相关分类源\n\n"

            # 分类未匹配或无结果，抓取全部源
            if not new_articles:
                logger.info("read_news: 抓取全部源...")
                try:
                    new_articles = await asyncio.wait_for(
                        service.fetch_all_feeds(), timeout=90.0
                    )
                except (asyncio.TimeoutError, Exception) as e:
                    logger.warning(f"read_news: 抓取失败: {type(e).__name__}: {e}")

            if not new_articles:
                recent = service.get_recent_articles(limit=limit)
                if recent:
                    summary = service.format_articles_summary(recent)
                    return True, f"暂时没有新文章，以下是最近的新闻：\n\n{summary}"
                return True, "目前没有可阅读的新闻。"

            logger.info(f"read_news: 获取到 {len(new_articles)} 篇文章")

            # 关键词二次过滤
            if keyword:
                kw = keyword.strip().lower()
                filtered = [
                    a for a in new_articles
                    if kw in a.title.lower() or kw in a.summary.lower()
                ]
                if filtered:
                    new_articles = filtered[:limit]
                else:
                    new_articles = new_articles[:limit]
                    topic_note += f"（未找到与「{keyword}」直接相关的文章，返回该分类最新新闻）\n\n"
            else:
                new_articles = new_articles[:limit]

            summary = service.format_articles_summary(new_articles)
            result = topic_note + f"📰 阅读完毕，发现 {len(new_articles)} 篇新闻：\n\n{summary}"
            logger.info(f"read_news: 完成，结果长度 {len(result)}")
            return True, result

        elif action == "detail":
            articles = service.get_recent_articles(limit=100)
            # 本地无缓存时自动触发抓取
            if not articles:
                logger.info("detail: 本地无缓存，自动抓取...")
                try:
                    await asyncio.wait_for(service.fetch_all_feeds(), timeout=90.0)
                except Exception as e:
                    logger.warning(f"detail: 自动抓取失败: {e}")
                articles = service.get_recent_articles(limit=100)
            if not articles:
                return True, "暂无文章，抓取也失败了。"
            # 通过编号或关键词定位文章
            target = None
            if keyword:
                # 尝试按编号
                try:
                    idx = int(keyword.strip()) - 1
                    if 0 <= idx < len(articles):
                        target = articles[idx]
                except ValueError:
                    pass
                # 按标题关键词
                if target is None:
                    kw = keyword.strip().lower()
                    for a in articles:
                        if kw in a.title.lower():
                            target = a
                            break
            if target is None:
                return True, f"未找到该文章。可传入文章编号（1-{len(articles)}）或标题关键词。"
            summary = target.summary[:500] + ("..." if len(target.summary) > 500 else "")
            detail = (
                f"📰 {target.title}\n"
                f"来源: {target.feed_title} | {target.published}\n"
                f"链接: {target.link}\n\n"
                f"{summary}"
            )
            return True, detail

        elif action == "list_feeds":
            config = service._config
            if config is None:
                return False, "配置未加载"
            urls = config.feeds.urls
            if not urls:
                return True, "当前没有订阅任何 RSS 源。"
            lines = ["📡 已订阅的 RSS 源：\n"]
            for i, url in enumerate(urls, 1):
                lines.append(f"  {i}. {url}")
            return True, "\n".join(lines)

        elif action == "search":
            if not keyword:
                return False, "搜索操作需要提供 keyword 参数"
            articles = service.get_recent_articles(limit=50)
            # 本地无缓存时自动触发抓取
            if not articles:
                logger.info("search: 本地无缓存，自动抓取...")
                try:
                    await asyncio.wait_for(service.fetch_all_feeds(), timeout=90.0)
                except Exception as e:
                    logger.warning(f"search: 自动抓取失败: {e}")
                articles = service.get_recent_articles(limit=50)
            kw = keyword.strip().lower()
            matched = [
                a for a in articles
                if kw in a.title.lower() or kw in a.summary.lower()
            ][:limit]
            if not matched:
                return True, f"未找到与「{keyword}」相关的文章。"
            summary = service.format_articles_summary(matched)
            return True, f"🔍 搜索「{keyword}」找到 {len(matched)} 篇文章：\n\n{summary}"

        elif action == "latest":
            articles = service.get_recent_articles(limit=limit)
            if not articles:
                return True, "暂无文章。请先使用 read_news action 抓取新闻。"
            summary = service.format_articles_summary(articles)
            return True, f"📰 最新 {len(articles)} 篇文章：\n\n{summary}"

        elif action == "stats":
            stats = service.get_feed_stats()
            if not stats:
                return True, "暂无统计数据。请先抓取新闻。"
            lines = ["📊 RSS 源统计：\n"]
            for name, count in stats.items():
                lines.append(f"  • {name}: {count} 篇")
            total = sum(stats.values())
            lines.append(f"\n  合计: {total} 篇")
            return True, "\n".join(lines)

        elif action == "categories":
            categories = service.get_categories()
            if not categories:
                return True, "暂未配置新闻分类。可在 config.toml 的 [feeds.categories] 中配置。"
            lines = ["📂 新闻分类：\n"]
            for cat_name, urls in categories.items():
                lines.append(f"  📁 {cat_name}（{len(urls)} 个源）")
                for url in urls:
                    lines.append(f"      • {url}")
            return True, "\n".join(lines)

        else:
            return False, f"未知操作: {action}。可选值: read_news, list_feeds, search, latest, detail, stats, categories"
