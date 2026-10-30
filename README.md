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
- Recent conversation, searchable original history, and editable Markdown
  personal dossiers; general knowledge remains in the knowledge base
- Telegram, Feishu/Lark, WeChat iLink, REST, and WebSocket adapters
- React dashboard for chat, conversations, memory, tools, schedules, monitoring,
  logs, and settings

## Requirements

- Python 3.12+
- Node.js 20+ for the frontend build (Node.js 24 used for this preview)
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

## Memory and further reading

Personal dossiers live under `data/personal_memory/`. Runtime retrieval separates answer facts from provenance: ordinary questions receive only ranked fact paragraphs, while evidence, history, and outcome questions can load provenance and original messages; stable global preferences form a small resident layer. Related original messages remain searchable, and the dashboard checks dossier revisions when saving. See [architecture](ARCHITECTURE.md) for the message path and [advanced operations](ADVANCED.md) for migration, backfill, and context budgets.

## Configuration

Secrets go in `.env`. Non-secret runtime choices go in `config.yaml`.
`config.yaml` is intentionally ignored by Git.

For the default `config.example.yaml`, the active primary model needs:

```env
OPENBOT_MODEL_API_KEY=your-model-api-key
```

Set the primary provider and model in `config.yaml` to your actual service.
The example leaves embeddings, reranking, and chat adapters disabled. To use
web search, add `TAVILY_API_KEY` to `.env`; enable and configure a chat adapter
only when you need that channel. For a Responses API setup, set
`OPENAI_API_KEY` in `.env` and configure:

```yaml
model:
  primary:
    provider: openai_responses
    model: your-responses-model
    api_key_env: OPENAI_API_KEY
    max_tokens: 16384
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
- Streaming is not implemented for `openai_responses`; the runtime uses its
  non-streaming API and still returns normal agent results

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

`enable_streaming` only controls whether the channel displays partial output.
The agent runtime separately chooses a streaming or non-streaming model API
based on the selected provider's capabilities.

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

## Mac desktop application (development)

`desktop/` contains an Apple Silicon Tauri 2 application sharing the Python Agent
and Web business logic. Its neutral interface accepts a model provider, endpoint,
model name and API key, plus a shared working directory. Configuration, conversations,
memory, file snapshots and runtime logs stay in a separate application data directory.

Closing the window keeps the service running; the menu bar can reopen it or quit.
Login startup defaults to off. Shell/Python require explicit authorization shared by
desktop, Web, channels and scheduled work. They use the current user's permissions;
the working directory is not a full sandbox. Stopping targets a specific execution
and does not undo effects that have already occurred.

Use the application's browser-console action to open its own local Web instance.
Browser credentials remain in page memory; refresh or a service restart requires
reopening from the application. Source deployments retain their existing startup
and Web access. See [desktop/README.md](desktop/README.md) for build and verification.
Settings include fallback/routed models, messaging channels, embeddings/reranking,
Tavily credentials, and WeChat QR login. Credentials remain private and are never
returned to the page. Before initial setup, a stopped standard schema-11 deployment
can be previewed and copied into an empty instance; imported channels and schedules
stay paused, and execution permissions must be granted again.

Native updates require a release endpoint and verification key built into the app.
This development build reports updates as unconfigured. The bundle is unsigned;
real accounts, signed/notarized distribution, actual upgrades, and clean-machine
acceptance remain unverified. See the desktop guide for supported import layouts.

### Isolated interactive Demo

An API-isolated interactive preview uses synthetic data. It does not read local
configuration, credentials, or history, and does not connect to models or channels.
It demonstrates history selection, streaming Markdown, simulated stopping, service
states, and the existing management pages. This preview toolchain uses Node.js 24;
the existing Web console remains available.

```bash
cd frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 5173
```

Open the [desktop preview](http://127.0.0.1:5173/desktop-demo/). Theme, language, and
management controls are at the bottom left; simulated states are at the top right.
Edits and authorization affect only in-memory fixtures and reset on reload. Stopping
in this entry is simulated; the real application uses backend execution and cancellation
state. Attachments are outside v1.

Assembly scripts provide standalone Python, production dependencies, rg and tokenizer
resources. Generated runtimes are not tracked by Git.

## Architecture

OpenBot is split into five main areas:

- `src/application/`: composition root, startup lifecycle, and message dispatch
- `src/agent/`: conversation assembly, ReAct runtime, research,
  scheduling, and verification
- `src/infrastructure/`: event bus, storage, model gateway, provider adapters,
  embeddings, reranking, and monitoring
- `src/tools/`: tool protocol, registry, and built-in tools
- `src/api/` and `frontend/`: FastAPI management API and React dashboard

Persistent runtime state is stored under `data/`, including SQLite databases,
logs, conversation exports, tool-output offloads, and local adapter state.
Follow a message from its adapter to the reply and background memory work in
[the architecture guide](ARCHITECTURE.md). For migration, backfill, and
context-budget operations, see [advanced operations](ADVANCED.md).

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

### `openai_responses` and streaming

`openai_responses` does not implement the model streaming API yet. OpenBot
detects that provider capability and uses its non-streaming API for model
rounds. Channel streaming remains a display setting:

```yaml
telegram:
  enable_streaming: false
```

## Security and Local Data

OpenBot is designed for trusted local use.

- The `bash` tool runs local shell commands with host permissions.
- Python snippets use the running service's Python environment; user site packages
  are not loaded. They still run with the current user's filesystem permissions.
- File tools operate under the project root.
- File mutations use explicit `create_file`, `append_file`, `edit_file`, and
  `replace_file` operations. `replace_file` requires the current SHA-256, which
  is available through `file_manager`'s `inspect_file` operation.
- Existing files are snapshotted under `data/file_snapshots/YYYY/MM/DD/` before
  mutation, and successful mutations are verified against their final content.
  A successful `bash` command is not treated as a structured file mutation.
- Management APIs and dashboard access are local-only by default.
- Webhook endpoints are only useful when explicitly exposed for platform
  callbacks.
- `.env` contains secrets and must stay local.
- `data/` contains runtime state, logs, conversations, file snapshots, tool
  outputs, and adapter state; keep it local unless you intentionally export a
  specific file.

## License

MIT
