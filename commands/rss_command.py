"""rss_plugin 命令：RSS 源管理。

支持的子命令：
    /rss 列表                    — 列出所有订阅的 RSS 源
    /rss 抓取                    — 立即抓取所有 RSS 源
    /rss 添加 <url>              — 添加新的 RSS 源
    /rss 删除 <url>              — 删除 RSS 源
    /rss 帮助                    — 显示帮助信息
"""

from __future__ import annotations

from src.app.plugin_system.api.log_api import get_logger
from src.app.plugin_system.api.send_api import send_text
from src.app.plugin_system.base import BaseCommand
from src.app.plugin_system.types import PermissionLevel

logger = get_logger("rss_plugin.rss_command")


class RSSCommand(BaseCommand):
    """RSS 源管理命令。"""

    command_name: str = "rss"
    command_description: str = "RSS 源管理：列表、抓取、添加、删除"
    permission_level: PermissionLevel = PermissionLevel.OWNER

    @classmethod
    def match(cls, parts: list[str]) -> int:
        """匹配命令名。"""
        if not parts:
            return 0
        if parts[0].lower() in ("rss", "新闻", "rss源"):
            return 1
        return 0

    async def _reply(self, text: str) -> None:
        """向当前聊天流发送文本回复。"""
        await send_text(text, stream_id=self.stream_id)

    async def execute(self, args: list[str]) -> tuple[bool, str]:
        """执行 RSS 命令。

        Args:
            args: 命令参数列表（不含命令名本身）

        Returns:
            (是否成功, 回复文本)
        """
        if not args:
            return await self._show_help()

        sub_cmd = args[0].lower()

        if sub_cmd in ("列表", "list", "ls"):
            return await self._list_feeds()
        elif sub_cmd in ("抓取", "fetch", "refresh"):
            return await self._fetch_feeds()
        elif sub_cmd in ("添加", "add"):
            return await self._add_feed(args[1:])
        elif sub_cmd in ("删除", "remove", "rm", "del"):
            return await self._remove_feed(args[1:])
        elif sub_cmd in ("帮助", "help"):
            return await self._show_help()
        else:
            await self._reply(f"未知子命令: {sub_cmd}\n")
            return await self._show_help()

    async def _show_help(self) -> tuple[bool, str]:
        """显示帮助信息。"""
        help_text = (
            "📖 RSS 源管理命令帮助\n\n"
            "可用子命令：\n"
            "  /rss 列表          — 列出所有订阅的 RSS 源\n"
            "  /rss 抓取          — 立即抓取所有 RSS 源的最新新闻\n"
            "  /rss 添加 <url>    — 添加新的 RSS 源\n"
            "  /rss 删除 <url>    — 删除指定 RSS 源\n"
            "  /rss 帮助          — 显示此帮助信息\n\n"
            "提示：机器人也可以通过 read_news action 主动阅读新闻。"
        )
        await self._reply(help_text)
        return True, help_text

    async def _list_feeds(self) -> tuple[bool, str]:
        """列出所有订阅源。"""
        from src.app.plugin_system.api.service_api import get_service
        from typing import cast
        from ..service import RSSFeedService

        service = get_service("rss_plugin:service:rss_feed")
        if service is None:
            msg = "❌ rss_plugin service 未加载"
            await self._reply(msg)
            return False, msg

        service = cast(RSSFeedService, service)
        config = service._config
        if config is None:
            msg = "❌ 配置未加载"
            await self._reply(msg)
            return False, msg

        urls = config.feeds.urls
        if not urls:
            msg = "📡 当前没有订阅任何 RSS 源。\n使用 /rss 添加 <url> 来添加。"
            await self._reply(msg)
            return True, msg

        lines = [f"📡 已订阅 {len(urls)} 个 RSS 源：\n"]
        for i, url in enumerate(urls, 1):
            lines.append(f"  {i}. {url}")

        # 显示统计
        stats = service.get_feed_stats()
        if stats:
            total = sum(stats.values())
            lines.append(f"\n📊 最近一次抓取: {total} 篇文章")

        msg = "\n".join(lines)
        await self._reply(msg)
        return True, msg

    async def _fetch_feeds(self) -> tuple[bool, str]:
        """立即抓取所有源。"""
        from src.app.plugin_system.api.service_api import get_service
        from typing import cast
        from ..service import RSSFeedService

        service = get_service("rss_plugin:service:rss_feed")
        if service is None:
            msg = "❌ rss_plugin service 未加载"
            await self._reply(msg)
            return False, msg

        service = cast(RSSFeedService, service)
        await self._reply("⏳ 正在抓取 RSS 源，请稍候...")

        articles = await service.fetch_all_feeds()

        if not articles:
            msg = "📰 抓取完成，暂无新文章。"
        else:
            summary = service.format_articles_summary(articles)
            msg = f"📰 抓取完成，发现 {len(articles)} 篇新文章：\n\n{summary}"

        await self._reply(msg)
        return True, msg

    async def _add_feed(self, args: list[str]) -> tuple[bool, str]:
        """添加 RSS 源。"""
        if not args:
            msg = "❌ 请提供 RSS 源 URL\n用法: /rss 添加 <url>"
            await self._reply(msg)
            return False, msg

        url = args[0].strip()
        if not url.startswith(("http://", "https://")):
            msg = "❌ 无效的 URL，需要以 http:// 或 https:// 开头"
            await self._reply(msg)
            return False, msg

        from src.app.plugin_system.api.service_api import get_service
        from typing import cast
        from ..service import RSSFeedService

        service = get_service("rss_plugin:service:rss_feed")
        if service is None:
            msg = "❌ rss_plugin service 未加载"
            await self._reply(msg)
            return False, msg

        service = cast(RSSFeedService, service)
        config = service._config
        if config is None:
            msg = "❌ 配置未加载"
            await self._reply(msg)
            return False, msg

        if url in config.feeds.urls:
            msg = f"⚠️ 该源已存在: {url}"
            await self._reply(msg)
            return False, msg

        # 验证 URL 是否可访问
        await self._reply("⏳ 验证 RSS 源...")
        try:
            test_articles = await service.fetch_feed(url, max_articles=1)
            config.feeds.urls.append(url)
            msg = f"✅ 添加成功: {url}\n验证获取到 {len(test_articles)} 篇文章"
        except Exception as e:
            msg = f"⚠️ 源添加成功但验证失败: {url}\n错误: {e}\n仍已添加，可稍后重试。"
            config.feeds.urls.append(url)

        await self._reply(msg)
        return True, msg

    async def _remove_feed(self, args: list[str]) -> tuple[bool, str]:
        """删除 RSS 源。"""
        if not args:
            msg = "❌ 请提供要删除的 RSS 源 URL\n用法: /rss 删除 <url>"
            await self._reply(msg)
            return False, msg

        url = args[0].strip()

        from src.app.plugin_system.api.service_api import get_service
        from typing import cast
        from ..service import RSSFeedService

        service = get_service("rss_plugin:service:rss_feed")
        if service is None:
            msg = "❌ rss_plugin service 未加载"
            await self._reply(msg)
            return False, msg

        service = cast(RSSFeedService, service)
        config = service._config
        if config is None:
            msg = "❌ 配置未加载"
            await self._reply(msg)
            return False, msg

        if url not in config.feeds.urls:
            msg = f"❌ 未找到该源: {url}"
            await self._reply(msg)
            return False, msg

        config.feeds.urls.remove(url)
        msg = f"✅ 已删除: {url}\n剩余 {len(config.feeds.urls)} 个订阅源"
        await self._reply(msg)
        return True, msg
