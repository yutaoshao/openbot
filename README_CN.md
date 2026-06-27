[English](README.md) | [中文](README_CN.md)

# OpenBot

OpenBot 是一个面向本机单用户场景的个人 AI Agent，用于个人自动化、多平台消息接入、工具执行、持久记忆、定时任务，以及本地优先的管理面板。

默认安全姿态是本地优先：运行时数据放在 `data/`，管理 API 默认只绑定本机，密钥放在 `.env`。

## 功能

- ReAct 风格 Agent 循环，支持工具调用和最终回复验证
- 模型网关支持 primary/fallback、重试、成本统计，以及可选 simple/complex 路由
- GPT-5 风格非 streaming Responses API provider，支持配置 `reasoning_effort` 和 `verbosity`
- OpenAI-compatible Chat Completions provider，适配 DashScope、DeepSeek、Kimi、Volcengine、Ollama、vLLM、LM Studio 等
- Anthropic Claude provider
- 内置工具：Web 搜索、网页抓取、文件操作、增量编辑、Shell、Python 执行、定时任务、深度研究
- 四层记忆：working、episodic、semantic、procedural
- Telegram、飞书/Lark、微信 iLink、REST、WebSocket 适配器
- React 管理面板：聊天、会话、记忆、工具、定时任务、监控、日志、设置

## 环境要求

- Python 3.12+
- Node.js 18+，用于前端构建
- [uv](https://docs.astral.sh/uv/)
- `rg` / ripgrep，需要在 `PATH` 中，供 `grep` 和 `glob` 工具使用
- 已启用模型、搜索、消息平台所需的 API key

## 快速开始

安装 Python 依赖并构建管理面板：

```bash
uv sync
cd frontend
npm install
npm run build
cd ..
```

创建本地密钥和配置文件：

```bash
cp .env.example .env
cp config.example.yaml config.yaml
```

编辑 `.env` 和 `config.yaml` 后启动 OpenBot：

```bash
uv run python main.py
```

管理面板地址：[http://127.0.0.1:8000/](http://127.0.0.1:8000/)。

本地后端开发时，可以使用自动重启脚本：

```bash
cp scripts/openbot-watch.example.sh scripts/openbot-watch.sh
chmod +x scripts/openbot-watch.sh
scripts/openbot-watch.sh
```

watcher 会在 `main.py`、源码、`.env`、`config.yaml`、`pyproject.toml` 或 `uv.lock` 变化时重启 `main.py`。它会忽略 `data/`，避免日志或运行时写入导致循环重启。

## 配置

密钥放在 `.env`。非敏感运行时选择放在 `config.yaml`。`config.yaml` 会被 Git 忽略。

当前 GPT-5.5 Responses 配置需要的最小模型相关密钥：

```env
OPENAI_API_KEY=sk-...
OPENBOT_EMBEDDING_API_KEY=...
OPENBOT_RERANKER_API_KEY=...
TAVILY_API_KEY=...
TELEGRAM_BOT_TOKEN=...
```

### GPT-5.5 Responses Provider

需要 GPT-5 风格 Responses API 参数时，使用 `openai_responses`，例如 reasoning effort 和 verbosity：

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
    connect_timeout: 30
    read_timeout: 600

telegram:
  enable_streaming: false
```

Provider 规则：

- `reasoning_effort`：`low`、`medium`、`high`、`xhigh`
- `verbosity`：`low`、`medium`、`high`
- `max_tokens` 会映射为 Responses API 的 `max_output_tokens`
- 该 provider 不传 `temperature`
- `base_url` 可以省略，使用 SDK 默认值；如果显式填写，必须以 `/v1` 结尾
- `api_key_env` 必须指向包含 API key 的环境变量
- `openai_responses` 还没有实现 streaming；使用它时请保持渠道 streaming 关闭

### Chat Completions Provider

实现 OpenAI Chat Completions 兼容接口的模型供应商使用 `openai_compatible`：

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

这是非 OpenAI 模型的最大兼容路径。

### Fallback 和 Routing

primary provider 失败后，OpenBot 可以尝试 fallback provider。可选 routing 可以在每次 Agent 运行时选择 `simple` 或 `complex` 档位。默认关闭 routing：

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

routing 关闭时，只有 `primary` 和 `fallback` 是 active path。

## 平台适配器

Telegram 最简单的本地用法是 polling：

```yaml
telegram:
  enabled: true
  mode: polling
  bot_token_env: TELEGRAM_BOT_TOKEN
  enable_streaming: false
```

如果当前模型 provider 不支持 streaming，`enable_streaming` 必须保持 `false`。

飞书/Lark webhook 模式需要公网回调地址：

```yaml
feishu:
  enabled: true
  mode: webhook
  app_id_env: FEISHU_APP_ID
  app_secret_env: FEISHU_APP_SECRET
  verification_token_env: FEISHU_VERIFICATION_TOKEN
  encrypt_key_env: FEISHU_ENCRYPT_KEY
```

在飞书事件订阅中配置 `https://<your-host>/webhook/feishu`，订阅
`im.message.receive_v1`。长连接模式不需要公网 webhook：

```yaml
feishu:
  enabled: true
  mode: long_connection
```

仍需配置 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET`。

微信适配器面向个人号 iLink 轮询工作流，用于私聊文本：

```yaml
wechat:
  enabled: true
  mode: ilink_polling
  state_path: data/wechat/ilink_state.json
```

```bash
uv run python -m src.channels.adapters.wechat_login
```

扫描生成的二维码，并确认 `data/wechat/ilink_state.json` 已生成。

## 开发

常用命令：

```bash
uv run ruff check .
uv run pytest -q
cd frontend && npm run build
```

开发时可以跑聚焦测试：

```bash
uv run pytest tests/core/test_config.py
uv run pytest tests/infrastructure/test_openai_responses_provider.py
```

以下文件和目录只应保留在本地：

- `.env`
- `config.yaml`
- `scripts/openbot-watch.sh`
- `data/`

不要提交运行时数据、日志、本地 provider endpoint 或本地 API key。

## 架构

OpenBot 分为五个主要区域：

- `src/application/`：组合根、启动生命周期、消息分发
- `src/agent/`：会话组装、ReAct 运行时、delegation、research、scheduling、verification
- `src/infrastructure/`：event bus、storage、model gateway、provider adapter、embedding、reranking、monitoring
- `src/tools/`：工具协议、工具注册表、内置工具
- `src/api/` 和 `frontend/`：FastAPI 管理 API 和 React 管理面板

持久运行时状态存放在 `data/`，包括 SQLite 数据库、日志、会话导出、工具输出落盘文件和本地适配器状态。

## 常见问题

### `openai_responses base_url must end with /v1`

OpenBot 会把 `base_url` 直接传给 OpenAI Python SDK。请使用 SDK API 根路径：

```yaml
base_url: https://api.example.com/v1
```

不要直接照搬 Codex 的 provider URL。Codex 有自己的 provider URL 语义。

### `Missing API key env ... for openai_responses provider`

active provider 已经实例化，但配置的环境变量为空或不存在。把它写入 `.env`：

```env
OPENAI_API_KEY=sk-...
```

### `openai_responses` 下 streaming 失败

`openai_responses` 尚未实现 streaming。关闭当前渠道的 streaming：

```yaml
telegram:
  enable_streaming: false
```

### 工具输出过长

超过 10,000 字符的工具结果会写入 `data/tool_outputs/YYYY/MM/DD/`。模型收到的是精简文件引用，而不是完整输出。

## 安全和本地数据

OpenBot 面向可信本机使用。

- `bash` 工具会以本机权限执行 shell 命令。
- 文件工具在项目根目录下工作。
- 管理 API 和面板默认只允许本机访问。
- Webhook endpoint 只有在你明确暴露给平台回调时才有意义。
- `.env` 包含密钥，必须保持本地。
- `data/` 包含运行时状态、日志、会话、工具输出和适配器状态；除非明确导出某个文件，否则保持本地。

## License

MIT
