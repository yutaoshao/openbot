[English](README.md) | [中文](README_CN.md)

# OpenBot

OpenBot is a local, single-user AI agent for personal automation. It combines
multi-platform messaging, tool execution, persistent memory, scheduled tasks,
and a loopback-first management dashboard.

The default posture is local-first: runtime data stays under `data/`,
management APIs bind to localhost by default, and secrets live in `.env`.

## Features

- ReAct-style agent loop with tool calling and final-response verification
- Model gateway with primary/fallback providers, retry, cost tracking, and
  optional simple/complex routing
- GPT-5 style non-streaming Responses API provider with configurable
  `reasoning_effort` and `verbosity`
- OpenAI-compatible Chat Completions provider for providers such as DashScope,
  DeepSeek, Kimi, Volcengine, Ollama, vLLM, and LM Studio
- Anthropic Claude provider
- Built-in tools for web search, web fetch, file operations, incremental edits,
  shell commands, Python execution, schedules, and deep research
- Four memory layers: working, episodic, semantic, and procedural
- Telegram, Feishu/Lark, WeChat iLink, REST, and WebSocket adapters
- React dashboard for chat, conversations, memory, tools, schedules, monitoring,
  logs, and settings

## Requirements

- Python 3.12+
- Node.js 18+ for the frontend build
- [uv](https://docs.astral.sh/uv/)
- `rg` / ripgrep on `PATH` for `grep` and `glob` tools
- API keys for the model/search/platform adapters you enable

## Quick Start

Install Python dependencies and build the dashboard:

```bash
uv sync
cd frontend && npm install && npm run build && cd ..
```

Create local secret and config files:

```bash
cp .env.example .env
cp config.example.yaml config.yaml
```

Edit `.env` and `config.yaml`, then start OpenBot:

```bash
uv run python main.py
```

Open the dashboard at [http://127.0.0.1:8000/](http://127.0.0.1:8000/).

For backend development with automatic restarts:

```bash
cp scripts/openbot-watch.example.sh scripts/openbot-watch.sh
chmod +x scripts/openbot-watch.sh && scripts/openbot-watch.sh
```

The watcher restarts `main.py` when source files, `.env`, `config.yaml`,
`pyproject.toml`, or `uv.lock` change. It ignores `data/` to avoid restart loops
from log or runtime writes.

## Configuration

Secrets go in `.env`. Non-secret runtime choices go in `config.yaml`.
`config.yaml` is intentionally ignored by Git.

Minimum model keys for the current GPT-5.5 Responses setup:

```env
OPENAI_API_KEY=sk-...
OPENBOT_EMBEDDING_API_KEY=...
OPENBOT_RERANKER_API_KEY=...
TAVILY_API_KEY=...
TELEGRAM_BOT_TOKEN=...
```

### GPT-5.5 Responses Provider

Use `openai_responses` when you want GPT-5 style Responses API parameters such
as reasoning effort and verbosity:

```yaml
model:
  primary:
    provider: openai_responses
    model: gpt-5.5
    base_url: https://api.example.com/v1
    api_key_env: OPENAI_API_KEY
    max_tokens: 16384
    reasoning_effort: high
    verbosity: low
telegram:
  enable_streaming: false
```

Provider rules:

- `reasoning_effort`: `low`, `medium`, `high`, or `xhigh`
- `verbosity`: `low`, `medium`, or `high`
- `max_tokens` maps to the Responses API `max_output_tokens`
- `temperature` is not sent by this provider
- `base_url` may be omitted for the SDK default; if set, it must end with `/v1`
- `api_key_env` must name an environment variable that contains the API key
- Streaming is not implemented for `openai_responses`; keep channel streaming
  disabled when using it

### Chat Completions Provider

Use `openai_compatible` for providers that implement the OpenAI Chat
Completions shape:

```yaml
model:
  primary:
    provider: openai_compatible
    model: example-model
    base_url: https://api.example.com/v1
    api_key_env: OPENBOT_MODEL_API_KEY
    max_tokens: 4096
    temperature: 0.7
```

This remains the broadest compatibility path for non-OpenAI providers.

### Fallback and Routing

OpenBot can try a fallback provider after primary provider failures. Optional
routing can select a configured `simple` or `complex` tier for each agent run.
Routing is disabled by default:

```yaml
model:
  fallback:
    provider: openai_compatible
    model: fallback-model
    base_url: https://api.example.com/v1
    api_key_env: FALLBACK_MODEL_API_KEY

  routing:
    enabled: false
    default_tier: complex
```

When routing is disabled, only `primary` and `fallback` are active.

## Platform Adapters

Telegram polling is the simplest local setup:

```yaml
telegram:
  enabled: true
  mode: polling
  bot_token_env: TELEGRAM_BOT_TOKEN
  enable_streaming: false
```

`enable_streaming` must stay `false` when the selected model provider does not
support streaming.

Feishu/Lark webhook mode requires a public callback endpoint:

```yaml
feishu:
  enabled: true
  mode: webhook
  app_id_env: FEISHU_APP_ID
  app_secret_env: FEISHU_APP_SECRET
  verification_token_env: FEISHU_VERIFICATION_TOKEN
  encrypt_key_env: FEISHU_ENCRYPT_KEY
```

Configure the callback URL as `https://<your-host>/webhook/feishu` and subscribe
to `im.message.receive_v1`. Long-connection mode avoids a public webhook URL:

```yaml
feishu:
  enabled: true
  mode: long_connection
```

Keep `FEISHU_APP_ID` and `FEISHU_APP_SECRET` configured.

The WeChat adapter targets a personal-account iLink polling workflow for
direct-message text chats:

```yaml
wechat:
  enabled: true
  mode: ilink_polling
  state_path: data/wechat/ilink_state.json
```

```bash
uv run python -m src.channels.adapters.wechat_login
```

Scan the generated QR code and confirm `data/wechat/ilink_state.json` exists.

## Development

Common commands:

```bash
uv run ruff check .
uv run pytest -q
cd frontend && npm run build
```

Use focused tests while iterating:

```bash
uv run pytest tests/core/test_config.py
uv run pytest tests/infrastructure/test_openai_responses_provider.py
```

Local-only files:

- `.env`
- `config.yaml`
- `scripts/openbot-watch.sh`
- `data/`

Do not commit runtime data, logs, local provider endpoints, or local API keys.

## Architecture

OpenBot is split into five main areas:

- `src/application/`: composition root, startup lifecycle, and message dispatch
- `src/agent/`: conversation assembly, ReAct runtime, delegation, research,
  scheduling, and verification
- `src/infrastructure/`: event bus, storage, model gateway, provider adapters,
  embeddings, reranking, and monitoring
- `src/tools/`: tool protocol, registry, and built-in tools
- `src/api/` and `frontend/`: FastAPI management API and React dashboard

Persistent runtime state is stored under `data/`, including SQLite databases,
logs, conversation exports, tool-output offloads, and local adapter state.

## Troubleshooting

### `openai_responses base_url must end with /v1`

OpenBot passes `base_url` directly to the OpenAI Python SDK. Use the SDK API
root:

```yaml
base_url: https://api.example.com/v1
```

Do not copy Codex provider URLs blindly; Codex has its own provider URL
semantics.

### `Missing API key env ... for openai_responses provider`

The active provider was instantiated, but the configured environment variable
was empty or missing. Add it to `.env`:

```env
OPENAI_API_KEY=sk-...
```

### Streaming fails with `openai_responses`

`openai_responses` does not implement streaming yet. Disable streaming for the
active channel:

```yaml
telegram:
  enable_streaming: false
```

## Security and Local Data

OpenBot is designed for trusted local use.

- The `bash` tool runs local shell commands with host permissions.
- File tools operate under the project root.
- Management APIs and dashboard access are local-only by default.
- Webhook endpoints are only useful when explicitly exposed for platform
  callbacks.
- `.env` contains secrets and must stay local.
- `data/` contains runtime state, logs, conversations, tool outputs, and adapter
  state; keep it local unless you intentionally export a specific file.

## License

MIT
