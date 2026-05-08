[English](README.md) | [中文](README_CN.md)

# OpenBot

一个面向本机单用户场景的个人 AI Agent，具备多平台消息接入、工具执行、四层记忆系统和本地优先的管理面板。

## 架构

| 层级 | 组件 |
|------|------|
| Application | Frontend (React)、REST API (FastAPI)、Msg Hub (Adapters) |
| Core | Agent (ReAct)、Sub-Agent、Scheduler、Deep Research |
| Memory | Working、Episodic、Semantic、Procedural |
| Tool | Registry、Protocol、Sandbox、Built-in Tools |
| Platform | Monitor、Config (Pydantic + YAML)、Logging (structlog) |
| Infrastructure | Event Bus、SQLite + sqlite-vec、Model Gateway (Multi-provider) |

## 快速开始

### 前置要求

- Python 3.12+
- Node.js 18+（用于前端）
- [uv](https://docs.astral.sh/uv/) 包管理器

### 安装

```bash
uv sync
cd frontend && npm install && npm run build && cd ..
```

### 配置

OpenBot 以本机单用户工作流为默认形态。管理页面、REST API 和 WebSocket 聊天默认只允许本机访问；平台回调相关的 webhook 端点则按适配器配置显式开放。

1. 复制 `.env.example` 为 `.env`，并填写 API Key：

```bash
cp .env.example .env
```

```env
ARK_API_KEY=your_volcengine_api_key
DASHSCOPE_API_KEY=your_dashscope_api_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TAVILY_API_KEY=your_tavily_api_key
FEISHU_APP_ID=your_feishu_app_id
FEISHU_APP_SECRET=your_feishu_app_secret
FEISHU_VERIFICATION_TOKEN=your_feishu_verification_token
FEISHU_ENCRYPT_KEY=your_feishu_encrypt_key
```

2. 复制示例配置，再编辑本地非敏感项（模型、参数、适配器等）。
   `config.yaml` 会被忽略，避免把本地 endpoint 和运行时选择提交到 GitHub。

```bash
cp config.example.yaml config.yaml
```

```yaml
telegram:
  enabled: true
  mode: polling
  bot_token_env: TELEGRAM_BOT_TOKEN
  enable_streaming: false

feishu:
  enabled: true
  mode: webhook
  app_id_env: FEISHU_APP_ID
  app_secret_env: FEISHU_APP_SECRET
  verification_token_env: FEISHU_VERIFICATION_TOKEN
  encrypt_key_env: FEISHU_ENCRYPT_KEY

wechat:
  enabled: false
  mode: ilink_polling
  state_path: data/wechat/ilink_state.json
  api_base_url: https://ilinkai.weixin.qq.com
  poll_interval: 2.0
  max_backoff: 30.0
```

### 运行

```bash
uv run python main.py
```

管理面板默认地址为 `http://127.0.0.1:8000/`。

本地后端开发时，如果希望修改代码或本地配置后自动重启，可以先复制 watcher 模板，
生成本地忽略的包装脚本：

```bash
cp scripts/openbot-watch.example.sh scripts/openbot-watch.sh
chmod +x scripts/openbot-watch.sh
scripts/openbot-watch.sh
```

watcher 会在 `main.py`、`src/`、`config.yaml`、`.env`、`pyproject.toml` 或
`uv.lock` 变化时重启完整的 `main.py` 进程。它会忽略 `data/` 下的运行时数据和
日志，避免日志写入导致循环重启。本地的 `scripts/openbot-watch.sh` 会被忽略，
因为它可能包含机器相关路径或 launchd 设置。

### 飞书 Webhook 配置

1. 在 `config.yaml` 中开启 `feishu.enabled`。
2. 在飞书开发者后台将事件订阅回调地址配置为：
   `https://<your-host>/webhook/feishu`
3. 在同一个事件订阅页面里，将校验 token 和 encrypt key 配置为：
   `FEISHU_VERIFICATION_TOKEN` 与 `FEISHU_ENCRYPT_KEY`
4. 订阅 `im.message.receive_v1` 事件。
5. 重启 OpenBot，并确认日志中出现 `app.feishu_ready`。

当前飞书支持范围有意保持精简：

- 入站消息：仅文本
- 出站消息：纯文本或单卡片 `lark_md`
- 安全策略：校验 token，并对加密回调做签名校验

### 飞书长连接配置

如果你想使用飞书的长连接模式，而不是公网 webhook：

1. 在 `config.yaml` 中将 `feishu.mode` 设置为 `long_connection`
2. 保留 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET`
3. 启动 OpenBot，并确认日志中出现：
   `app.feishu_ready` 且 `mode=long_connection`
4. 在飞书开发者后台选择长连接 / WebSocket 事件接收模式，而不是开发者服务器回调

当前长连接模式支持：

- 不需要公网回调地址
- OpenBot 运行时不依赖 webhook token 和 encrypt key
- 入站消息仍然仅支持文本
- 出站仍然复用当前的文本 / interactive card 发送逻辑

手工验证清单：

- 使用飞书的 URL 验证流程，确认回调验证成功
- 给 Bot 发送一条文本消息，确认 OpenBot 能收到并回复
- 请求一条 markdown 较重的回复，确认飞书侧收到 interactive card
- 故意配置错误的 token 或 encrypt key，确认 webhook 会被拒绝

### 微信个人号（iLink）配置

内置微信适配器当前面向个人号 iLink 路线，首版范围固定为：

- 单账号
- 私聊文本
- 轮询模式，不需要公网 webhook
- 不支持独立主动推送

1. 在 `config.yaml` 中开启 `wechat.enabled`。
2. 在本机运行登录命令：

```bash
uv run python -m src.channels.adapters.wechat_login
```

3. 扫描生成的二维码，并在微信里确认登录。
4. 确认 `data/wechat/ilink_state.json` 已生成，日志中出现 `app.wechat_ready`。

当前 v1 限制：

- 入站仅支持私聊文本
- 出站仅支持基于活跃会话上下文的回复
- 图片/语音/文件等非文本消息会收到固定提示
- `target_platform="wechat"` 的定时任务或其他后台主动推送会显式失败

手工验证清单：

- 运行登录命令后确认 `data/wechat/login.png` 已生成
- 从微信发送一条文本消息，确认 OpenBot 能收到并回复
- 发送一条非文本消息，确认微信侧收到“仅支持文本消息”的提示
- 创建一个投递到微信的 schedule，确认系统明确提示不支持主动推送

## 项目结构

```
openbot/
├── main.py                          # 应用入口
├── config.example.yaml              # 示例配置；复制为本地 config.yaml 使用
├── src/
│   ├── application/                 # 组合根与运行时编排
│   │   ├── container.py             # Application 对象图
│   │   ├── bootstrap.py             # 运行时服务与工具注册
│   │   ├── message_dispatch.py      # 入站消息分发
│   │   └── lifecycle.py             # API / 适配器 / scheduler 启停
│   ├── infrastructure/              # Event Bus、Database、Model Gateway
│   │   ├── event_bus.py             # 支持通配符的异步 pub/sub
│   │   ├── database.py              # SQLite schema 与 migration
│   │   ├── storage/                 # Repository 分包
│   │   ├── model_gateway.py         # 多模型供应商网关（routing / retry / fallback / streaming）
│   │   ├── model_routing.py         # simple / complex 确定性路由分类器
│   │   ├── embedding.py             # Embedding 服务（OpenAI-compatible + DashScope）
│   │   ├── reranker.py              # Reranker 服务（SiliconFlow / Jina / Cohere）
│   │   └── providers/
│   │       ├── anthropic.py         # Claude API（chat + streaming）
│   │       └── openai_compat.py     # OpenAI-compatible（Volcengine、DeepSeek 等）
│   ├── core/                        # Config、Logging、Monitor
│   │   ├── config.py                # 使用 Pydantic 的配置与环境变量解析
│   │   ├── logging.py               # structlog 配置（console / JSON）
│   │   └── monitor.py               # 指标采集（延迟、token、成本）
│   ├── tools/                       # Tool 协议与注册表
│   │   ├── registry.py              # Tool 协议、ToolResult、ToolRegistry
│   │   └── builtin/
│   │       ├── web_search.py        # Tavily Web 搜索
│   │       ├── web_fetch.py         # 网页抓取与正文提取
│   │       ├── code_executor.py     # 沙箱 Python 执行
│   │       └── file_manager.py      # Workspace 文件操作
│   ├── agent/                       # Agent Core
│   │   ├── agent.py                 # ReAct 推理主循环（streaming + non-streaming）
│   │   ├── conversation/            # 会话编排分包
│   │   │   ├── __init__.py          # 会话包导出
│   │   │   ├── manager.py           # 会话管理（上下文组装）
│   │   │   ├── prompt_builder.py    # 结合记忆的 prompt 组装
│   │   │   ├── shared_timeline.py   # 跨平台最近消息时间线
│   │   │   └── task_state_store.py  # 单会话受保护状态
│   │   ├── runtime/                 # Agent 执行期辅助模块
│   │   │   ├── __init__.py          # Runtime 包导出
│   │   │   ├── stream.py            # 主 streamed ReAct 循环
│   │   │   ├── finalize.py          # 回复后持久化与收尾
│   │   │   └── tool_executor.py     # 工具调用与 hook 集成
│   │   ├── delegation/              # 子代理委派域
│   │   │   ├── __init__.py          # Delegation 导出
│   │   │   └── manager.py           # 带 scoped tools 的并行子任务委派
│   │   ├── research/                # 研究域
│   │   │   ├── __init__.py          # Research 导出
│   │   │   └── engine.py            # 多轮检索与饱和判断研究引擎
│   │   ├── skills/                  # 技能发现/加载域
│   │   │   ├── __init__.py          # Skills 导出
│   │   │   └── registry.py          # Skill registry 与 load_skill 工具
│   │   ├── scheduling/              # 定时执行域
│   │   │   ├── __init__.py          # Scheduler 导出
│   │   │   └── scheduler.py         # 基于 APScheduler 的定时任务执行
│   │   ├── prompts/                 # Prompt 片段域
│   │   │   ├── __init__.py          # Prompt 导出
│   │   │   └── fragments.py         # Harness prompt 片段
│   │   ├── coordination/            # 跨请求执行协调域
│   │   │   ├── __init__.py          # Coordination 导出
│   │   │   └── execution.py         # 按用户串行执行协调
│   │   ├── state/                   # Agent 任务状态域
│   │   │   ├── __init__.py          # State 导出
│   │   │   └── task_state.py        # 结构化任务状态对象
│   │   └── verification/            # 最终回复校验域
│   │       ├── __init__.py          # Verification 导出
│   │       └── responses.py         # 模糊回复重写辅助
│   ├── memory/                      # 四层记忆系统
│   │   ├── working.py               # 工作记忆与压缩
│   │   ├── episodic/                # 对话归档与摘要
│   │   │   ├── __init__.py          # Episodic facade 导出
│   │   │   ├── service.py           # Episodic 记忆服务
│   │   │   └── helpers.py           # Episodic 辅助工具
│   │   ├── semantic/                # 知识提取与向量检索
│   │   │   ├── __init__.py          # Semantic facade 导出
│   │   │   ├── service.py           # Semantic 记忆服务
│   │   │   ├── queries.py           # Semantic 查询/抽取 mixin
│   │   │   ├── mutations.py         # Semantic 写入/合并 mixin
│   │   │   └── helpers.py           # Semantic 辅助工具
│   │   └── procedural/              # 用户偏好与行为模式
│   │       ├── __init__.py          # Procedural facade 导出
│   │       ├── service.py           # Procedural 记忆服务
│   │       └── helpers.py           # Procedural 辅助工具
│   ├── channels/                    # 消息平台适配层
│   │   ├── hub.py                   # 消息路由中心
│   │   ├── types.py                 # UnifiedMessage、MessageContent、StreamingAdapter
│   │   ├── markdown.py              # Markdown 转 Telegram HTML
│   │   └── adapters/
│   │       ├── telegram.py          # Telegram（polling + webhook + streaming draft）
│   │       ├── feishu.py            # 飞书 / Lark（webhook + interactive card）
│   │       └── web.py               # 前端 WebSocket 适配器
│   └── api/                         # REST API
│       ├── app.py                   # FastAPI app factory
│       ├── websocket.py             # WebSocket streaming chat handler
│       └── routes/
│           ├── chat.py              # POST /api/chat
│           ├── conversations.py     # CRUD /api/conversations
│           ├── knowledge.py         # CRUD /api/knowledge + semantic search
│           ├── tools.py             # GET/PUT /api/tools
│           ├── schedules.py         # CRUD /api/schedules
│           ├── metrics.py           # GET /api/metrics/*
│           ├── settings.py          # GET/PUT /api/settings
│           └── webhook.py           # POST /webhook/telegram, /webhook/feishu
└── frontend/                        # React 管理面板
    └── src/
        ├── app/
        │   ├── App.tsx              # 路由定义
        │   ├── Layout.tsx           # 应用壳（侧边栏 + 主题切换）
        │   └── route-loaders.ts     # 懒加载路由与预加载钩子
        ├── lib/
        │   ├── api.ts               # API 客户端与 WebSocket 辅助
        │   └── markdown.ts          # Chat Markdown 渲染
        ├── components/
        │   ├── Icon.tsx             # 共享图标系统
        │   └── TopbarQuickSearch.tsx # 全局工作区搜索
        └── pages/
            ├── dashboard.tsx        # 指标总览与图表
            ├── chat.tsx             # Chat 界面（DeepSeek 风格）
            ├── conversations.tsx    # 会话历史浏览
            ├── memory.tsx           # 知识库 CRUD
            ├── tools.tsx            # 工具状态与配置
            ├── scheduler.tsx        # 定时任务管理
            ├── monitoring.tsx       # 延迟 / token / 成本图表
            └── settings.tsx         # 运行时配置
```

## 功能

### Agent

- ReAct 推理循环，支持多轮工具调用
- 通过 `run_stream()` 异步生成器输出流式结果
- 支持带 scoped tool registry 的子 Agent 委派与并行执行
- 基于 cron 的定时任务调度，并持久化到数据库
- 多轮深度研究与信息饱和检测

### Memory

| 层级 | 用途 | 生命周期 |
|------|------|----------|
| Working | 当前会话上下文 | 会话期 |
| Episodic | 对话摘要与向量 | 持久化 |
| Semantic | 提取出的知识与向量检索 | 持久化（TTL） |
| Procedural | 用户偏好与行为模式 | 持久化 |

### Tools

| 工具 | 说明 |
|------|------|
| `web_search` | 通过 Tavily 进行网页搜索 |
| `web_fetch` | 抓取网页并提取正文 |
| `code_executor` | 在沙箱子进程中执行 Python |
| `file_manager` | 读取、写入、列出 workspace 文件 |

### 平台适配器

| 平台 | 模式 | 特性 |
|------|------|------|
| Telegram | Polling / Webhook | Streaming draft、Markdown-to-HTML、访问控制 |
| Feishu | Webhook | 加密回调校验、interactive card、自动刷新 token |
| WeChat | iLink 轮询 | 二维码登录、长轮询文本会话、基于 context token 回复 |
| Web | WebSocket | 流式聊天、REST fallback |

### Dashboard

支持亮色 / 暗色主题，共 8 个页面：Dashboard、Chat、Conversations、Memory、Tools、Scheduler、Monitoring、Settings。

### 模型支持

支持任意 OpenAI-compatible API 端点，包括：

- Volcengine（Doubao / Kimi）
- DashScope（Qwen）
- DeepSeek
- Anthropic（Claude）
- 通过 Ollama / vLLM 运行的本地模型

支持主模型 + 回退模型，并具备自动重试和指数退避。

可选模型路由可以在每次 Agent 运行时，根据确定性的 prompt / tool 规则选择
`simple` 或 `complex` 档位。路由负责先选哪个模型档位；fallback 仍只处理
provider 失败后的回退。

## 测试

```bash
uv run ruff check .
uv run pytest -q
```

## License

MIT
