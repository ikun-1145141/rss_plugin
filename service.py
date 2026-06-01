"""rss_plugin 服务实现。

核心功能：
- 抓取并解析 RSS/Atom 源
- 文章去重与历史记录管理
- 新闻摘要生成
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.core.components.base.service import BaseService
from src.kernel.logger import get_logger

from .config import RSSPluginConfig

logger = get_logger("rss_plugin")

# 避免在模块顶层导入 feedparser/httpx，仅在运行时按需导入
_feedparser = None
_httpx = None


def _ensure_deps() -> None:
    """延迟导入外部依赖。"""
    global _feedparser, _httpx
    if _feedparser is None:
        import feedparser
        _feedparser = feedparser
    if _httpx is None:
        import httpx
        _httpx = httpx


@dataclass(frozen=True, slots=True)
class Article:
    """一篇文章的数据。"""

    feed_url: str
    feed_title: str
    title: str
    link: str
    summary: str
    published: str
    fetched_at: float

    @property
    def article_id(self) -> str:
        """基于链接生成唯一 ID。"""
        return self.link.strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "feed_url": self.feed_url,
            "feed_title": self.feed_title,
            "title": self.title,
            "link": self.link,
            "summary": self.summary,
            "published": self.published,
            "fetched_at": self.fetched_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Article:
        return cls(
            feed_url=data["feed_url"],
            feed_title=data["feed_title"],
            title=data["title"],
            link=data["link"],
            summary=data.get("summary", ""),
            published=data.get("published", ""),
            fetched_at=data.get("fetched_at", 0.0),
        )


class RSSFeedService(BaseService):
    """RSS 源抓取与管理服务。"""

    service_name: str = "rss_feed"
    service_description: str = "RSS/Atom 源抓取、解析、去重与历史记录管理"

    def __init__(self, plugin: Any) -> None:
        super().__init__(plugin)
        self._history: dict[str, float] = {}  # article_id -> fetched_at
        self._articles: list[Article] = []
        self._history_path: Path | None = None
        self._lock = asyncio.Lock()

    @property
    def _config(self) -> RSSPluginConfig | None:
        """从插件获取配置。"""
        config = getattr(self.plugin, "config", None)
        if isinstance(config, RSSPluginConfig):
            return config
        return None

    async def initialize(self) -> None:
        """初始化服务，加载历史记录。"""
        config = self._config
        if config is None:
            return

        history_file = config.storage.history_file
        self._history_path = Path(history_file)
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_history()
        logger.info(f"rss_plugin 服务已初始化，历史记录: {len(self._history)} 条")

    def _load_history(self) -> None:
        """从磁盘加载历史记录。"""
        if self._history_path is None or not self._history_path.exists():
            return
        try:
            data = json.loads(self._history_path.read_text(encoding="utf-8"))
            self._history = {k: float(v) for k, v in data.items()}
            self._cleanup_old_history()
        except Exception as e:
            logger.warning(f"加载 RSS 历史记录失败: {e}")

    def _save_history(self) -> None:
        """保存历史记录到磁盘。"""
        if self._history_path is None:
            return
        try:
            self._history_path.write_text(
                json.dumps(self._history, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"保存 RSS 历史记录失败: {e}")

    def _cleanup_old_history(self) -> None:
        """清理过期的历史记录。"""
        if self._config is None:
            return
        max_age = self._config.storage.max_history_age_days
        cutoff = time.time() - max_age * 86400
        before = len(self._history)
        self._history = {k: v for k, v in self._history.items() if v > cutoff}
        after = len(self._history)
        if before != after:
            logger.debug(f"清理了 {before - after} 条过期历史记录")

    def is_new_article(self, article: Article) -> bool:
        """判断文章是否为新文章。"""
        return article.article_id not in self._history

    def mark_read(self, article: Article) -> None:
        """标记文章为已读。"""
        self._history[article.article_id] = article.fetched_at

    async def fetch_feed(self, feed_url: str, max_articles: int = 10) -> list[Article]:
        """抓取单个 RSS 源。

        Args:
            feed_url: RSS 源 URL
            max_articles: 最多返回的文章数

        Returns:
            新文章列表（已去重）
        """
        _ensure_deps()
        articles: list[Article] = []
        now = time.time()

        try:
            async with _httpx.AsyncClient(
                timeout=_httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=10.0),
                follow_redirects=True,
            ) as client:
                logger.info(f"开始抓取 RSS: {feed_url}")
                resp = await client.get(feed_url, headers={"User-Agent": "MoFox-RSS/1.0"})
                resp.raise_for_status()
                logger.info(f"抓取成功: {feed_url} ({len(resp.text)} bytes)")

            feed = _feedparser.parse(resp.text)
            feed_title = feed.feed.get("title", feed_url)

            for entry in feed.entries[:max_articles]:
                link = entry.get("link", "").strip()
                if not link:
                    continue

                title = entry.get("title", "无标题").strip()
                summary = entry.get("summary", entry.get("description", "")).strip()
                # 去除 HTML 标签（简单处理）
                if "<" in summary:
                    import re
                    summary = re.sub(r"<[^>]+>", "", summary).strip()
                # 截断过长摘要
                if len(summary) > 1000:
                    summary = summary[:1000] + "..."

                published = entry.get("published", entry.get("updated", ""))

                article = Article(
                    feed_url=feed_url,
                    feed_title=str(feed_title),
                    title=title,
                    link=link,
                    summary=summary,
                    published=str(published),
                    fetched_at=now,
                )

                if self.is_new_article(article):
                    articles.append(article)

        except Exception as e:
            logger.error(f"抓取 RSS 源失败 [{feed_url}]: {type(e).__name__}: {e}")

        logger.info(f"RSS {feed_url} 完成，获取 {len(articles)} 篇新文章")
        return articles

    async def fetch_all_feeds(self) -> list[Article]:
        """抓取所有订阅的 RSS 源。

        Returns:
            所有新文章列表
        """
        if self._config is None:
            logger.warning("rss_plugin 配置未加载")
            return []

        urls = self._config.feeds.urls
        max_articles = self._config.feeds.max_articles_per_feed

        all_articles: list[Article] = []
        tasks = [self.fetch_feed(url, max_articles) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"抓取任务异常 [{urls[i]}]: {result}")
            elif isinstance(result, list):
                all_articles.extend(result)

        # 标记为已读（带超时，避免锁竞争导致卡住）
        try:
            acquired = await asyncio.wait_for(self._lock.acquire(), timeout=5.0)
            try:
                for article in all_articles:
                    self.mark_read(article)
                self._articles = all_articles
                self._cleanup_old_history()
                self._save_history()
            finally:
                self._lock.release()
        except asyncio.TimeoutError:
            logger.warning("fetch_all_feeds: 获取锁超时，跳过历史保存")
            self._articles = all_articles
            self._save_history()

        logger.info(f"RSS 抓取完成，共 {len(all_articles)} 篇新文章")
        return all_articles

    def get_categories(self) -> dict[str, list[str]]:
        """获取所有分类及其对应的源 URL。"""
        if self._config is None:
            return {}
        return dict(self._config.feeds.categories)

    def match_category(self, topic: str) -> list[str] | None:
        """根据关键词匹配分类，返回对应的源 URL 列表。

        支持中英文关键词匹配。例如 "科技" 能匹配 "tech" 分类。

        Args:
            topic: 用户输入的主题关键词

        Returns:
            匹配到的源 URL 列表，未匹配返回 None
        """
        if self._config is None:
            return None
        categories = self._config.feeds.categories
        topic_lower = topic.strip().lower()

        # 中文关键词 → 英文分类名 映射
        zh_en_map: dict[str, list[str]] = {
            "科技": ["tech", "technology", "science"],
            "国际": ["international", "world", "global"],
            "国内": ["domestic", "china", "local"],
            "财经": ["finance", "economy", "business"],
            "体育": ["sports"],
            "娱乐": ["entertainment"],
        }

        for cat_name, urls in categories.items():
            cat_lower = cat_name.lower()
            # 直接匹配
            if topic_lower in cat_lower or cat_lower in topic_lower:
                return urls
            # 中文关键词匹配英文分类
            for zh_kw, en_kws in zh_en_map.items():
                if zh_kw in topic_lower and cat_lower in en_kws:
                    return urls

        return None

    async def fetch_by_urls(self, urls: list[str]) -> list[Article]:
        """抓取指定 URL 列表的 RSS 源。

        Args:
            urls: 要抓取的 RSS 源 URL 列表

        Returns:
            新文章列表
        """
        if self._config is None:
            logger.warning("rss_plugin 配置未加载")
            return []

        max_articles = self._config.feeds.max_articles_per_feed
        all_articles: list[Article] = []
        tasks = [self.fetch_feed(url, max_articles) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"抓取任务异常 [{urls[i]}]: {result}")
            elif isinstance(result, list):
                all_articles.extend(result)

        # 标记为已读（带超时，避免锁竞争导致卡住）
        logger.info(f"fetch_by_urls: 抓取完成，{len(all_articles)} 篇文章，准备保存...")
        try:
            acquired = await asyncio.wait_for(self._lock.acquire(), timeout=5.0)
            try:
                for article in all_articles:
                    self.mark_read(article)
                self._cleanup_old_history()
                self._save_history()
            finally:
                self._lock.release()
            logger.info("fetch_by_urls: 历史记录已保存")
        except asyncio.TimeoutError:
            logger.warning("fetch_by_urls: 获取锁超时，跳过历史保存")

        return all_articles

    def get_recent_articles(self, limit: int = 10) -> list[Article]:
        """获取最近抓取的文章。"""
        return self._articles[:limit]

    def get_feed_stats(self) -> dict[str, int]:
        """获取各源的文章数量统计。"""
        stats: dict[str, int] = {}
        for article in self._articles:
            stats[article.feed_title] = stats.get(article.feed_title, 0) + 1
        return stats

    def format_articles_summary(self, articles: list[Article], max_length: int = 1500) -> str:
        """将文章列表格式化为摘要文本。"""
        if not articles:
            return "暂无新文章。"

        lines: list[str] = []
        total_len = 0

        for i, article in enumerate(articles, 1):
            short_summary = article.summary[:100] + ("..." if len(article.summary) > 100 else "")
            line = f"{i}. {article.title}（{article.feed_title}）\n   {short_summary}\n   🔗 {article.link}"

            if total_len + len(line) > max_length and lines:
                lines.append(f"\n... 还有 {len(articles) - len(lines)} 篇未显示")
                break
            lines.append(line)
            total_len += len(line)

        return "\n".join(lines)
