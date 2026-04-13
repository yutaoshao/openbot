[English](README.md) | [中文](README_CN.md)

# OpenBot

一个具备多平台消息接入、工具执行、四层记忆系统和管理面板的个人 AI Agent。

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

2. 编辑 `config.yaml` 配置非敏感项（模型、参数、适配器等）。

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
```

### 运行

```bash
uv run python main.py
```

管理面板默认地址为 `http://127.0.0.1:8000/`。

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

## 项目结构

```
openbot/
├── main.py                          # 应用入口
├── config.yaml                      # 非敏感配置
├── src/
│   ├── infrastructure/              # Event Bus、Database、Model Gateway
│   │   ├── event_bus.py             # 支持通配符的异步 pub/sub
│   │   ├── database.py              # SQLite schema 与 migration
│   │   ├── storage.py               # Repository 层（conversations、knowledge 等）
│   │   ├── model_gateway.py         # 多模型供应商网关（retry / fallback / streaming）
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
│   │   ├── conversation.py          # 会话管理（上下文组装）
│   │   ├── sub_agent.py             # 带 scoped tools 的并行子任务委派
│   │   ├── scheduler.py             # 基于 APScheduler 的定时任务执行
│   │   └── deep_research.py         # 多轮检索与饱和判断研究引擎
│   ├── memory/                      # 四层记忆系统
│   │   ├── working.py               # 工作记忆与压缩
│   │   ├── episodic.py              # 对话归档与摘要
│   │   ├── semantic.py              # 知识提取与向量检索
│   │   └── procedural.py            # 用户偏好与行为模式
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
        ├── App.tsx                  # 路由定义
        ├── lib/
        │   ├── api.ts               # API 客户端与 WebSocket 辅助
        │   └── markdown.ts          # Chat Markdown 渲染
        ├── components/
        │   └── Layout.tsx           # 应用壳（侧边栏 + 主题切换）
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

## 测试

```bash
uv run ruff check .
uv run pytest -q
```

## License

MIT
