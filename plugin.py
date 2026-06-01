"""rss_plugin 插件入口。

加载后会注册一个 scheduler 周期任务：定时抓取 RSS 源获取最新新闻。
支持机器人主动调用 read_news action 来"看新闻"。
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.components import BasePlugin, register_plugin
from src.kernel.concurrency import get_task_manager
from src.kernel.logger import get_logger

from .commands.rss_command import RSSCommand
from .config import RSSPluginConfig
from .service import RSSFeedService
from .tool import RSSQueryTool


logger = get_logger("rss_plugin")

# --- System Prompt Reminder ---
_TARGET_REMINDER_BUCKET = "actor"
_TARGET_REMINDER_NAME = "关于新闻阅读的能力"
_RSS_USAGE_REMINDER = (
    "你拥有阅读新闻的能力。你可以通过 query_rss 工具（action=read_news）主动去查看最新新闻，"
    "了解世界上正在发生的事情。这个能力可以让你在聊天中分享有趣的新闻、"
    "提供话题相关的背景信息，或者在闲暇时主动了解时事。\n"
    "使用建议：\n"
    "1. 当聊天中提到某个话题时，你可以主动去查找相关新闻\n"
    "2. 在日常对话中，偶尔分享有趣的新闻可以丰富聊天内容\n"
    "3. 当被问到「最近有什么新闻」时，使用 query_rss 工具（action=read_news）来获取\n"
    "4. 使用 /rss 命令可以管理订阅的 RSS 源"
)


def build_rss_actor_reminder(plugin: Any) -> str:
    """构建 rss_plugin 的 actor reminder。"""
    return _RSS_USAGE_REMINDER


def sync_rss_actor_reminder(plugin: Any) -> str:
    """同步 rss_plugin 的 actor reminder。"""
    from src.core.prompt import get_system_reminder_store

    store = get_system_reminder_store()
    reminder_content = build_rss_actor_reminder(plugin)

    store.set(
        _TARGET_REMINDER_BUCKET,
        name=_TARGET_REMINDER_NAME,
        content=reminder_content,
    )
    logger.debug("rss_plugin actor reminder 已同步")
    return reminder_content


@register_plugin
class RSSPlugin(BasePlugin):
    """RSS 新闻阅读器插件。"""

    plugin_name: str = "rss_plugin"
    plugin_description: str = "RSS 源获取与新闻阅读，让机器人可以主动看新闻"
    plugin_version: str = "1.0.0"

    configs: list[type] = [RSSPluginConfig]
    dependent_components: list[str] = []

    def __init__(self, config: RSSPluginConfig | None = None) -> None:
        super().__init__(config)
        self._schedule_ids: list[str] = []
        self._register_task_id: str | None = None

    def get_components(self) -> list[type]:
        """返回插件包含的所有组件类。"""
        return [
            RSSFeedService,
            RSSQueryTool,
            RSSCommand,
        ]

    async def on_plugin_loaded(self) -> None:
        """插件加载完成后的初始化逻辑。"""
        logger.info("rss_plugin 插件已加载")

        # 同步 actor reminder
        sync_rss_actor_reminder(self)

        # 延迟初始化 service（等待 service_manager 就绪）
        self._register_task_id = asyncio.create_task(
            self._deferred_init()
        )

    async def _deferred_init(self) -> None:
        """延迟初始化：等待 service_manager 就绪后初始化 service 并注册定时任务。"""
        from src.app.plugin_system.api.service_api import get_service
        from src.kernel.concurrency import get_task_manager
        from typing import cast

        # 等待 service_manager 就绪
        await asyncio.sleep(2)

        service = get_service("rss_plugin:service:rss_feed")
        if service is not None:
            service = cast(RSSFeedService, service)
            await service.initialize()
            logger.info("rss_plugin service 初始化完成")
        else:
            logger.warning("rss_plugin service 未找到，跳过初始化")
            return

        # 注册定时任务
        config = self.config if isinstance(self.config, RSSPluginConfig) else None
        if config and config.scheduler.enabled:
            await self._wait_and_register_schedule(config)

        logger.info(f"rss_plugin 全部初始化完成，订阅源: {len(config.feeds.urls) if config else 0} 个")

    async def _wait_and_register_schedule(self, config: RSSPluginConfig) -> None:
        """等待 scheduler 就绪后注册定时抓取任务。"""
        try:
            from src.kernel.scheduler import get_unified_scheduler, TriggerType

            scheduler = get_unified_scheduler()
            interval = config.scheduler.interval_seconds

            schedule_id = await scheduler.create_schedule(
                callback=self._scheduled_fetch,
                trigger_type=TriggerType.TIME,
                trigger_config={
                    "delay_seconds": 60,  # 启动后 60 秒首次执行
                    "interval_seconds": interval,
                },
                is_recurring=True,
                task_name="rss_plugin_fetch",
            )
            self._schedule_ids.append(schedule_id)
            logger.info(f"rss_plugin 定时任务已注册，间隔 {interval} 秒")

        except Exception as e:
            logger.warning(f"rss_plugin 注册定时任务失败: {e}")

    async def _scheduled_fetch(self) -> None:
        """定时抓取回调。"""
        from src.app.plugin_system.api.service_api import get_service
        from typing import cast

        service = get_service("rss_plugin:service:rss_feed")
        if service is None:
            logger.warning("定时抓取失败: service 未加载")
            return

        service = cast(RSSFeedService, service)
        articles = await service.fetch_all_feeds()

        if articles:
            logger.info(f"定时抓取完成: {len(articles)} 篇新文章")
        else:
            logger.debug("定时抓取完成: 无新文章")

    async def on_plugin_unloaded(self) -> None:
        """插件卸载时的清理逻辑。"""
        # 取消注册中的定时任务
        if self._register_task_id and not self._register_task_id.done():
            self._register_task_id.cancel()

        for schedule_id in self._schedule_ids:
            try:
                from src.kernel.scheduler import get_unified_scheduler
                scheduler = get_unified_scheduler()
                await scheduler.remove_schedule(schedule_id)
            except Exception:
                pass

        # 清理 actor reminder
        from src.core.prompt import get_system_reminder_store
        store = get_system_reminder_store()
        store.delete(_TARGET_REMINDER_BUCKET, _TARGET_REMINDER_NAME)

        logger.info("rss_plugin 插件已卸载")
