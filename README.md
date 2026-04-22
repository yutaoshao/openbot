[English](README.md) | [中文](README_CN.md)

# OpenBot

Local single-user AI agent with multi-platform messaging, tool execution, 4-tier memory, and a loopback-first management dashboard.

## Architecture

| Layer | Components |
|------|------------|
| Application | Frontend (React), REST API (FastAPI), Msg Hub (Adapters) |
| Core | Agent (ReAct), Sub-Agent, Scheduler, Deep Research |
| Memory | Working, Episodic, Semantic, Procedural |
| Tool | Registry, Protocol, Sandbox, Built-in Tools |
| Platform | Monitor, Config (Pydantic + YAML), Logging (structlog) |
| Infrastructure | Event Bus, SQLite + sqlite-vec, Model Gateway (Multi-provider) |

## Quick Start

### Prerequisites

- Python 3.12+
- Node.js 18+ (for frontend)
- [uv](https://docs.astral.sh/uv/) package manager

### Installation

```bash
uv sync
cd frontend && npm install && npm run build && cd ..
```

### Configuration

OpenBot is designed for a local single-user workflow. By default, management pages, REST APIs, and WebSocket chat stay on local-only access, while webhook endpoints remain explicitly configurable for platform callbacks.

1. Copy `.env.example` to `.env` and fill in API keys:

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

2. Edit `config.yaml` for non-secret settings (model, parameters, adapters).

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

### Run

```bash
uv run python main.py
```

The dashboard is available at `http://127.0.0.1:8000/`.

### Feishu Webhook Setup

1. Enable the `feishu.enabled` switch in `config.yaml`.
2. In the Feishu developer console, configure the event subscription callback URL as:
   `https://<your-host>/webhook/feishu`
3. In the same event subscription page, set the verification token and encrypt key to match:
   `FEISHU_VERIFICATION_TOKEN` and `FEISHU_ENCRYPT_KEY`
4. Subscribe to `im.message.receive_v1`.
5. Restart OpenBot and confirm the logs contain `app.feishu_ready`.

Current Feishu support is intentionally narrow:

- Incoming messages: text-only
- Outgoing messages: plain text or single-card `lark_md`
- Security: verification token plus encrypted callback signature validation

### Feishu Long Connection Setup

If you prefer Feishu's long-connection mode and do not want a public webhook URL:

1. Set `feishu.mode: long_connection` in `config.yaml`.
2. Keep `FEISHU_APP_ID` and `FEISHU_APP_SECRET` configured.
3. Start OpenBot and confirm the logs contain:
   `app.feishu_ready` with `mode=long_connection`
4. In the Feishu developer console, use the long-connection / WebSocket event mode instead of developer-server callbacks.

Current long-connection support:

- No public callback URL required
- No webhook verification token or encrypt key required by OpenBot runtime
- Incoming messages still limited to text-only
- Outgoing messages still use the same text / interactive card sender

Manual validation checklist:

- Use Feishu's URL verification flow and confirm the callback succeeds
- Send a text message to the bot and verify OpenBot receives and replies
- Ask for a markdown-heavy answer and verify Feishu receives an interactive card
- Deliberately misconfigure the token or encrypt key and verify the webhook is rejected

### WeChat Personal Account (iLink) Setup

The built-in WeChat adapter currently targets the personal-account iLink route:

- Single account only
- Direct-message text chats only
- Polling mode only, no public webhook required
- No standalone proactive sends

1. Enable `wechat.enabled` in `config.yaml`.
2. Run the local login command:

```bash
uv run python -m src.channels.adapters.wechat_login
```

3. Scan the generated QR code and confirm login in WeChat.
4. Confirm `data/wechat/ilink_state.json` exists and logs contain `app.wechat_ready`.

Current v1 limitations:

- Inbound: direct-message text only
- Outbound: replies inside active conversations only
- Unsupported media types receive a fixed text notice
- Scheduler and other background proactive sends to `target_platform="wechat"` fail explicitly

Manual validation checklist:

- Run the login command and confirm `data/wechat/login.png` is generated
- Send a text message from WeChat and verify OpenBot replies
- Send a non-text message and verify WeChat receives the text-only warning
- Create a schedule targeting WeChat and verify proactive send is reported as unsupported

## Project Structure

```
openbot/
├── main.py                          # Application entrypoint
├── config.yaml                      # Non-secret configuration
├── src/
│   ├── application/                 # Composition root + runtime orchestration
│   │   ├── container.py             # Application object graph
│   │   ├── bootstrap.py             # Runtime service + tool registration
│   │   ├── message_dispatch.py      # Incoming message dispatch
│   │   └── lifecycle.py             # API/adapters/scheduler startup
│   ├── infrastructure/              # Event Bus, Database, Model Gateway
│   │   ├── event_bus.py             # Async pub/sub with wildcard matching
│   │   ├── database.py              # SQLite schema and migrations
│   │   ├── storage/                 # Repository layer packages
│   │   ├── model_gateway.py         # Multi-provider LLM gateway (retry/fallback/streaming)
│   │   ├── embedding.py             # Embedding service (OpenAI-compat + DashScope)
│   │   ├── reranker.py              # Reranker service (SiliconFlow/Jina/Cohere)
│   │   └── providers/
│   │       ├── anthropic.py         # Claude API (chat + streaming)
│   │       └── openai_compat.py     # OpenAI-compatible (Volcengine, DeepSeek, etc.)
│   ├── core/                        # Config, Logging, Monitor
│   │   ├── config.py                # Pydantic config with declarative secret resolution
│   │   ├── logging.py               # structlog setup (console/JSON)
│   │   └── monitor.py               # Metrics collector (latency, tokens, cost)
│   ├── tools/                       # Tool Protocol and Registry
│   │   ├── registry.py              # Tool Protocol, ToolResult, ToolRegistry
│   │   └── builtin/
│   │       ├── web_search.py        # Tavily web search
│   │       ├── web_fetch.py         # Web page fetch + content extraction
│   │       ├── code_executor.py     # Sandboxed Python execution
│   │       └── file_manager.py      # Workspace file operations
│   ├── agent/                       # Agent Core
│   │   ├── agent.py                 # ReAct reasoning loop (streaming + non-streaming)
│   │   ├── conversation/            # Conversation assembly package
│   │   │   ├── __init__.py          # Conversation package exports
│   │   │   ├── manager.py           # Conversation manager (context assembly)
│   │   │   ├── prompt_builder.py    # Memory-enriched prompt assembly
│   │   │   ├── shared_timeline.py   # Cross-platform recent timeline
│   │   │   └── task_state_store.py  # Per-conversation protected state
│   │   ├── runtime/                 # Agent turn execution helpers
│   │   │   ├── __init__.py          # Runtime package exports
│   │   │   ├── stream.py            # Main streamed ReAct loop
│   │   │   ├── finalize.py          # Post-response persistence/finalization
│   │   │   └── tool_executor.py     # Tool invocation + hook integration
│   │   ├── delegation/              # Sub-agent delegation domain
│   │   │   ├── __init__.py          # Delegation exports
│   │   │   └── manager.py           # Parallel subtask delegation with scoped tools
│   │   ├── research/                # Research domain
│   │   │   ├── __init__.py          # Research exports
│   │   │   └── engine.py            # Multi-round research engine with saturation detection
│   │   ├── skills/                  # Skill discovery/loading domain
│   │   │   ├── __init__.py          # Skill exports
│   │   │   └── registry.py          # Skill registry + load_skill tool
│   │   ├── scheduling/              # Scheduled execution domain
│   │   │   ├── __init__.py          # Scheduler exports
│   │   │   └── scheduler.py         # APScheduler-based cron task execution
│   │   ├── prompts/                 # Prompt assembly fragments
│   │   │   ├── __init__.py          # Prompt exports
│   │   │   └── fragments.py         # Harness prompt fragments
│   │   ├── coordination/            # Cross-request execution coordination
│   │   │   ├── __init__.py          # Coordination exports
│   │   │   └── execution.py         # Per-user execution serialization
│   │   ├── state/                   # Agent task state domain
│   │   │   ├── __init__.py          # State exports
│   │   │   └── task_state.py        # Structured task state objects
│   │   └── verification/            # Final-response verification
│   │       ├── __init__.py          # Verification exports
│   │       └── responses.py         # Vague-response rewriting helpers
│   ├── memory/                      # 4-Tier Memory System
│   │   ├── working.py               # Working memory + compression
│   │   ├── episodic/                # Conversation archival + summaries
│   │   │   ├── __init__.py          # Episodic facade exports
│   │   │   ├── service.py           # Episodic memory service
│   │   │   └── helpers.py           # Episodic helper utilities
│   │   ├── semantic/                # Knowledge extraction + vector search
│   │   │   ├── __init__.py          # Semantic facade exports
│   │   │   ├── service.py           # Semantic memory service
│   │   │   ├── queries.py           # Semantic recall/extraction mixins
│   │   │   ├── mutations.py         # Semantic mutation/storage mixins
│   │   │   └── helpers.py           # Semantic helper utilities
│   │   └── procedural/              # User preferences + behavior patterns
│   │       ├── __init__.py          # Procedural facade exports
│   │       ├── service.py           # Procedural memory service
│   │       └── helpers.py           # Procedural helper utilities
│   ├── channels/                    # Messaging Adapters
│   │   ├── hub.py                   # Message routing hub
│   │   ├── types.py                 # UnifiedMessage, MessageContent, StreamingAdapter
│   │   ├── markdown.py              # Markdown to Telegram HTML converter
│   │   └── adapters/
│   │       ├── telegram.py          # Telegram (polling + webhook + streaming draft)
│   │       ├── feishu.py            # Feishu/Lark (webhook + interactive card)
│   │       └── web.py               # WebSocket adapter for frontend
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
└── frontend/                        # React Dashboard
    └── src/
        ├── app/
        │   ├── App.tsx              # Route definitions
        │   ├── Layout.tsx           # App shell (sidebar + theme toggle)
        │   └── route-loaders.ts     # Lazy route loaders + preload hooks
        ├── lib/
        │   ├── api.ts               # API client + WebSocket helper
        │   └── markdown.ts          # Markdown renderer for chat
        ├── components/
        │   ├── Icon.tsx             # Shared icon system
        │   └── TopbarQuickSearch.tsx # Global workspace search
        └── pages/
            ├── dashboard.tsx        # Metrics overview + charts
            ├── chat.tsx             # Chat interface (DeepSeek-style)
            ├── conversations.tsx    # Conversation history browser
            ├── memory.tsx           # Knowledge base CRUD
            ├── tools.tsx            # Tool status + config
            ├── scheduler.tsx        # Scheduled task management
            ├── monitoring.tsx       # Latency/token/cost charts
            └── settings.tsx         # Runtime configuration
```

## Features

### Agent

- ReAct reasoning loop with multi-turn tool calling
- Streaming output via `run_stream()` async generator
- Sub-agent delegation with scoped tool registries and parallel execution
- Cron-based task scheduler with DB persistence
- Multi-round deep research with saturation detection

### Memory

| Tier | Purpose | Lifecycle |
|------|---------|-----------|
| Working | Active conversation context | Session |
| Episodic | Conversation summaries + embeddings | Persistent |
| Semantic | Extracted knowledge with vector search | Persistent (TTL) |
| Procedural | User preferences + behavior patterns | Persistent |

### Tools

| Tool | Description |
|------|-------------|
| `web_search` | Search the web via Tavily API |
| `web_fetch` | Fetch and extract content from web pages |
| `code_executor` | Execute Python code in sandboxed subprocess |
| `file_manager` | Read, write, and list files in workspace |

### Platform Adapters

| Platform | Mode | Features |
|----------|------|----------|
| Telegram | Polling / Webhook | Streaming draft, Markdown-to-HTML, access control |
| Feishu | Webhook | Encrypted callback validation, interactive card messages, auto token refresh |
| WeChat | iLink polling | QR login, long-poll text chats, context-token replies |
| Web | WebSocket | Streaming chat, REST fallback |

### Dashboard

Light/dark theme, 8 pages: Dashboard, Chat, Conversations, Memory, Tools, Scheduler, Monitoring, Settings.

### Model Support

Any OpenAI-compatible API endpoint, including:

- Volcengine (Doubao/Kimi)
- DashScope (Qwen)
- DeepSeek
- Anthropic (Claude)
- Local models via Ollama / vLLM

Primary + fallback models with automatic retry and exponential backoff.

## Testing

```bash
uv run ruff check .
uv run pytest -q
```

## License

MIT
