"""rss_plugin 配置。

配置文件默认路径：config/plugins/rss_plugin/config.toml
"""

from __future__ import annotations

from typing import ClassVar

from src.core.components.base.config import BaseConfig, Field, SectionBase, config_section


class RSSPluginConfig(BaseConfig):
    """rss_plugin 配置。"""

    config_name: ClassVar[str] = "config"
    config_description: ClassVar[str] = "RSS 新闻阅读器插件配置"

    @config_section("feeds")
    class FeedsSection(SectionBase):
        """RSS 源配置。"""

        urls: list[str] = Field(
            default=[
                "https://feeds.bbci.co.uk/news/world/rss.xml",
                "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
                "https://hnrss.org/frontpage",
                "https://36kr.com/feed",
            ],
            description="订阅的 RSS 源 URL 列表",
        )
        max_articles_per_feed: int = Field(
            default=10,
            description="每次抓取每个源最多获取的文章数",
        )
        categories: dict[str, list[str]] = Field(
            default={
                "international": [
                    "https://feeds.bbci.co.uk/news/world/rss.xml",
                    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
                ],
                "tech": [
                    "https://hnrss.org/frontpage",
                    "https://36kr.com/feed",
                ],
            },
            description=(
                "新闻分类映射。键为分类名（英文，如 'tech'、'international'），值为该分类对应的 RSS 源 URL 列表。\n"
                "用户提问时会根据关键词匹配分类，自动选择对应的源进行阅读。"
            ),
        )

    @config_section("scheduler")
    class SchedulerSection(SectionBase):
        """调度相关配置。"""

        interval_seconds: int = Field(
            default=1800,
            description="定时抓取间隔（秒），默认 30 分钟",
        )
        enabled: bool = Field(
            default=True,
            description="是否启用定时抓取",
        )

    @config_section("storage")
    class StorageSection(SectionBase):
        """存储相关配置。"""

        history_file: str = Field(
            default="data/rss_plugin/feed_history.json",
            description="已读文章历史记录文件路径",
        )
        max_history_age_days: int = Field(
            default=7,
            description="历史记录保留天数，超过此天数的记录将被清理",
        )

    @config_section("behavior")
    class BehaviorSection(SectionBase):
        """行为配置。"""

        auto_share: bool = Field(
            default=False,
            description="定时抓取后是否自动将新闻分享到聊天",
        )
        summary_max_length: int = Field(
            default=500,
            description="新闻摘要最大长度（字符）",
        )
        language_filter: str = Field(
            default="",
            description="语言过滤（留空=不过滤）。可选值：zh, en, ja 等",
        )

    # 显式声明配置节字段（Pydantic 要求）
    feeds: FeedsSection = Field(default_factory=FeedsSection)
    scheduler: SchedulerSection = Field(default_factory=SchedulerSection)
    storage: StorageSection = Field(default_factory=StorageSection)
    behavior: BehaviorSection = Field(default_factory=BehaviorSection)
