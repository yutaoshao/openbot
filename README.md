# OpenBot

Personal AI agent with multi-platform messaging, tool execution, 4-tier memory, and management dashboard.

## Architecture

```
Application    Frontend (React)  |  REST API (FastAPI)  |  Msg Hub (Adapters)
Core           Agent (ReAct)  |  Sub-Agent  |  Scheduler  |  Deep Research
Memory         Working  |  Episodic  |  Semantic  |  Procedural
Tool           Registry  |  Protocol  |  Sandbox  |  Built-in Tools
Platform       Monitor  |  Config (Pydantic + YAML)  |  Logging (structlog)
Infrastructure Event Bus  |  SQLite + sqlite-vec  |  Model Gateway (Multi-provider)
```

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
```

2. Edit `config.yaml` for non-secret settings (model, parameters, adapters).

### Run

```bash
uv run python main.py
```

The dashboard is available at `http://127.0.0.1:8000/`.

## Project Structure

```
openbot/
├── main.py                          # Application entrypoint
├── config.yaml                      # Non-secret configuration
├── src/
│   ├── infrastructure/              # Event Bus, Database, Model Gateway
│   │   ├── event_bus.py             # Async pub/sub with wildcard matching
│   │   ├── database.py              # SQLite schema and migrations
│   │   ├── storage.py               # Repository layer (conversations, knowledge, etc.)
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
│   │   ├── conversation.py          # Conversation manager (context assembly)
│   │   ├── sub_agent.py             # Parallel subtask delegation with scoped tools
│   │   ├── scheduler.py             # APScheduler-based cron task execution
│   │   └── deep_research.py         # Multi-round research engine with saturation detection
│   ├── memory/                      # 4-Tier Memory System
│   │   ├── working.py               # Working memory + compression
│   │   ├── episodic.py              # Conversation archival + summaries
│   │   ├── semantic.py              # Knowledge extraction + vector search
│   │   └── procedural.py            # User preferences + behavior patterns
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
        ├── App.tsx                  # Route definitions
        ├── lib/
        │   ├── api.ts               # API client + WebSocket helper
        │   └── markdown.ts          # Markdown renderer for chat
        ├── components/
        │   └── Layout.tsx           # App shell (sidebar + theme toggle)
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
| Feishu | Webhook | Interactive card messages, auto token refresh |
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
