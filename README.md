# OpenBot

Personal AI agent with multi-platform messaging, tool execution, and memory system.

## Architecture

```
Application:    Msg Hub (Adapters) | REST API (FastAPI) | Frontend (React)
Core:           Agent Loop (ReAct) | Sub-Agent | Memory (4-tier) | Scheduler
Tool:           ToolRegistry | Tool Protocol | Sandbox | Built-in Tools
Platform:       Monitor | Config (Pydantic + YAML) | Logging (structlog)
Infrastructure: Event Bus | SQLite + sqlite-vec | Model Gateway (Multi-provider)
```

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager

### Installation

```bash
uv sync
```

### Configuration

1. Copy `.env.example` to `.env` and fill in your API keys:

```bash
cp .env.example .env
```

```env
ARK_API_KEY=your_volcengine_api_key
DASHSCOPE_API_KEY=your_dashscope_api_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TAVILY_API_KEY=your_tavily_api_key
```

2. Edit `config.yaml` for non-secret settings (model selection, parameters, etc.)

### Run

```bash
uv run python main.py
```

## Project Structure

```
openbot/
├── main.py                             # Application entrypoint
├── config.yaml                         # Non-secret configuration
├── src/
│   ├── infrastructure/                 # Event Bus, Model Gateway, Providers
│   │   ├── event_bus.py                # Async pub/sub with wildcard matching
│   │   ├── model_gateway.py            # Multi-provider LLM gateway with retry/fallback
│   │   └── providers/                  # LLM provider implementations
│   │       ├── anthropic.py            # Claude API
│   │       └── openai_compat.py        # OpenAI-compatible (Volcengine, DeepSeek, etc.)
│   ├── platform/                       # Config, Logging
│   │   ├── config.py                   # Pydantic config with declarative secret resolution
│   │   └── logging.py                  # structlog setup (console/JSON)
│   ├── tools/                          # Tool Protocol and Registry
│   │   ├── registry.py                 # Tool Protocol, ToolResult, ToolRegistry
│   │   └── builtin/                    # Built-in tools
│   │       ├── web_search.py           # Tavily web search
│   │       ├── web_fetch.py            # Web page fetch + content extraction
│   │       ├── code_executor.py        # Sandboxed Python execution
│   │       └── file_manager.py         # Workspace file operations
│   ├── agent/                          # Agent Core
│   │   └── agent.py                    # ReAct reasoning loop with tool calling
│   └── channels/                       # Messaging Adapters
│       ├── hub.py                      # Message routing hub
│       ├── types.py                    # UnifiedMessage, MessageContent
│       └── adapters/
│           └── telegram.py             # Telegram polling adapter
└── docs/
    └── todo.md                         # Implementation plan
```

## Built-in Tools

| Tool | Description |
|------|-------------|
| `web_search` | Search the web via Tavily API |
| `web_fetch` | Fetch and extract content from web pages |
| `code_executor` | Execute Python code in sandboxed subprocess |
| `file_manager` | Read, write, and list files in workspace |

## Model Support

Any OpenAI-compatible API endpoint is supported, including:

- Volcengine (Doubao/Kimi)
- DashScope (Qwen/GLM)
- DeepSeek
- Moonshot
- Anthropic (Claude)
- Local models via Ollama / vLLM

Configure primary and fallback models in `config.yaml`. The gateway handles automatic retry and fallback.

## Development Status

- [x] Phase 1: Config, Logging, Event Bus, Model Gateway, Agent (single-turn), Telegram
- [x] Phase 2: Tool Protocol, 4 Built-in Tools, Multi-turn Agent Loop
- [ ] Phase 3: Database, Storage, 4-tier Memory, Conversation Manager
- [ ] Phase 4: REST API, Monitor, Frontend Dashboard
- [ ] Phase 5: Sub-Agent, Scheduler, DeepResearch, Feishu

See [docs/todo.md](docs/todo.md) for the full implementation plan.

## License

MIT
