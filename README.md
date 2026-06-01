# RSS 新闻阅读器插件

> 让你的 MoFox 机器人可以主动看新闻！

## 功能特性

- 📡 **RSS 源订阅** — 支持任意 RSS/Atom 源
- ⏰ **定时抓取** — 可配置间隔自动抓取新闻
- 🤖 **主动阅读** — 机器人通过 LLM Tool 主动"看新闻"，结果会触发回复
- 🏷️ **分类路由** — 按主题关键词自动选择对应分类的 RSS 源
- 🔍 **关键词搜索** — 按主题过滤新闻
- 📄 **文章详情** — 可指定某篇文章查看完整摘要和链接
- 📋 **命令管理** — `/rss` 命令管理订阅源
- 📝 **去重存储** — 自动去重，历史记录可配置保留天数

## 安装

将 `rss_plugin/` 文件夹放到机器人的 `plugins/` 目录下，确保已安装依赖：

```bash
pip install feedparser httpx
```

## 组件说明

| 组件类型 | 名称 | 说明 |
|---------|------|------|
| Service | `rss_feed` | 核心服务：抓取、解析、去重、存储、分类匹配 |
| Tool | `query_rss` | LLM 工具：抓取新闻、搜索、查看详情、查询源信息 |
| Command | `rss` | 用户命令：管理 RSS 源 |

## Tool 操作

`query_rss` 工具支持以下操作：

| action | 说明 | keyword 参数 |
|--------|------|-------------|
| `read_news` | 实时抓取最新新闻并返回摘要 | 可选，用于匹配分类源+关键词过滤 |
| `search` | 搜索已缓存的文章（无缓存时自动抓取）| 搜索关键词 |
| `detail` | 查看某篇文章的完整摘要和链接 | 文章编号或标题关键词 |
| `latest` | 获取本地最新文章 | — |
| `list_feeds` | 列出所有订阅源 | — |
| `stats` | 获取统计信息 | — |
| `categories` | 查看新闻分类及对应源 | — |

## 命令使用

```
/rss 列表          — 查看所有订阅的 RSS 源
/rss 抓取          — 立即抓取所有源的最新新闻
/rss 添加 <url>    — 添加新的 RSS 源
/rss 删除 <url>    — 删除 RSS 源
/rss 帮助          — 显示帮助信息
```

## 配置说明

配置文件路径：`config/plugins/rss_plugin/config.toml`

```toml
[feeds]
urls = [
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    "https://hnrss.org/frontpage",
    "https://36kr.com/feed",
]
max_articles_per_feed = 10

[feeds.categories]
international = [
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
]
tech = [
    "https://hnrss.org/frontpage",
    "https://36kr.com/feed",
]

[scheduler]
interval_seconds = 1800  # 30 分钟抓取一次
enabled = true

[storage]
history_file = "data/rss_plugin/feed_history.json"
max_history_age_days = 7

[behavior]
auto_share = false         # 是否自动分享到聊天
summary_max_length = 500   # 摘要最大长度
language_filter = ""       # 语言过滤（留空=不过滤）
```

## 推荐的 RSS 源

| 源 | URL | 分类 |
|---|-----|------|
| BBC 世界新闻 | `https://feeds.bbci.co.uk/news/world/rss.xml` | international |
| 纽约时报 | `https://rss.nytimes.com/services/xml/rss/nyt/World.xml` | international |
| Hacker News | `https://hnrss.org/frontpage` | tech |
| 36氪 | `https://36kr.com/feed` | tech |
| V2EX | `https://www.v2ex.com/index.xml` | tech |
| GitHub Trending | `https://rsshub.app/github/trending/daily/any` | tech |

## 工作流程

1. **定时抓取**：按配置间隔自动抓取所有订阅源
2. **去重存储**：已读文章记录到历史文件，避免重复
3. **主动阅读**：机器人通过 `query_rss` 工具（`read_news`）主动查看新闻
4. **分类路由**：传入关键词时自动匹配对应分类的源，减少无关内容
5. **分享聊天**：工具结果触发 LLM 回复，机器人将新闻分享到当前对话中

## 文件结构

```
rss_plugin/
├── __init__.py        # 包入口
├── plugin.py          # 插件主类 + 生命周期 + scheduler
├── manifest.json      # 组件声明
├── config.py          # 配置模型（含分类配置）
├── service.py         # RSS 抓取/解析/去重/存储/分类匹配
├── tool.py            # LLM Tool: 抓取、搜索、详情、查询
├── commands/
│   ├── __init__.py
│   └── rss_command.py # /rss 管理命令
└── README.md          # 本文档
```
