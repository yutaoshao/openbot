# Mac 桌面端构建与验证（开发阶段）

当前包含正式 `/desktop/` 入口、隔离 `/desktop-demo/`、Tauri 2 服务托管、独立 Python 运行时、服务/渠道配置、离线复制导入、原生更新及诊断工具。真实外部账号、正式更新托管、签名公证和干净机器验收尚未完成。

## 装配独立运行时

构建机需要 Python 3.12+ 与 uv。从仓库根目录执行：

```bash
.venv/bin/python desktop/scripts/assemble_runtime.py
```

固定下载源、版本和 SHA256 记录在 `probe/runtime-sources.json`。装配器校验独立 CPython 3.12.16、官方 arm64 rg 15.2.0 和真实 cl100k/o200k 编码表，并从 uv.lock 导出无 dev 依赖的带 hash 清单，安装 84 个生产 wheel。保留 Python、rg 和 wheels 的许可证与元数据。默认缓存位于 `/private/tmp/openbot-runtime-downloads`，产物位于忽略的 `desktop/runtime`，不安装全局工具，不读取用户 `.env`、`config.yaml` 或 `data/`。

已有生成运行时时加 `--replace`，旧目录会移入缓存下 backups，不会永久删除。`build-manifest.json` 记录下载源/hash、uv.lock、requirements 和本次应用 Python 源文件的 hash。应用源码快照只复制 `.py`，排除缓存和指向源树外的符号链接；不得用开发虚拟环境或宿主 Python 链接代替独立发行版。

独立运行时的离线探测命令（仓库根目录）：

```bash
env -i PATH=/usr/bin:/bin \
  TIKTOKEN_CACHE_DIR="$PWD/desktop/runtime/tokenizer-cache" \
  desktop/runtime/bin/python3 -I -B desktop/probe/runtime_probe.py \
  --source-root desktop/runtime/app --rg "$PWD/desktop/runtime/bin/rg" \
  --expected-runtime desktop/runtime --tokenizer-cache desktop/runtime/tokenizer-cache
```

只使用临时合成数据，直接调用现有 Database 初始化/迁移和 CodeExecutor；不调用 load_config，不启动模型、渠道、调度或完整应用。临时数据库在退出时清理；输出 JSON，任一检查失败退出 1。真实 tokenizer 缓存先校验 hash，再加载编码器，缺失或不符时拒绝，不在探测期间下载。

2026-10-29 在 arm64/macOS 26.5 开发机通过 8 项离线检查：真实 cl100k/o200k hash 与编码往返、Python 3.12.16 的解释器/基前缀位于运行时内、主要依赖导入、schema 11/sqlite-vec v0.1.6、tiktoken 原生引擎、显式 Python 子进程、现有 CodeExecutor 的真实解释器路径与隔离状态、rg 文件搜索。CodeExecutor 检查同时断言 user_site_enabled 和 user_site_on_path 均为 false，不读取宿主用户 site 文件。核心实现使用 -s 禁用子进程用户 site，不能假设父进程 -I 会自动继承；也不能仅版本相同就声称使用了随包解释器。

## Tauri 工程与构建

Tauri 正式窗口加载独立 HTML `/desktop/index.html`，与 Web 共用 React/业务代码；开发地址为 `http://127.0.0.1:5173/desktop/`。先在 frontend 构建正式入口或启动 Vite 5173。CLI 锁定为 2.12.4，Cargo.lock 实际锁定 Tauri 2.12.5；稳定应用标识为 `com.openbot.desktop`，当前版本保持 0.1.0。

本机以隔离目录安装 Rust 1.99.1，使用官方 arm64 rustup-init 并校验同源 SHA256；没有修改用户 shell 配置、系统 PATH 或用户 ~/.cargo。Command Line Tools、SDK 26.2、Apple clang 17 可用。以下命令从 desktop 执行，只影响当前 shell：

```bash
export RUSTUP_HOME=/private/tmp/openbot-rustup
export CARGO_HOME=/private/tmp/openbot-cargo
export CARGO_TARGET_DIR=/private/tmp/openbot-desktop-target
export PATH="$CARGO_HOME/bin:$PATH"
npm ci
cargo fmt --manifest-path src-tauri/Cargo.toml -- --check
cargo check --manifest-path src-tauri/Cargo.toml --target aarch64-apple-darwin --locked
cargo test --manifest-path src-tauri/Cargo.toml --target aarch64-apple-darwin --locked --offline
npm run tauri -- build --debug --target aarch64-apple-darwin --bundles app --no-sign -- --locked --offline
```

P1 预览曾完成 debug `.app` 构建与运行时重定位检查；正式服务托管改动后需重新检查并构建。新产物将位于 `/private/tmp/openbot-desktop-target/aarch64-apple-darwin/debug/bundle/macos/OpenBot.app`，不得拿旧 `OpenBot Preview.app` 代替正式入口验证。`app-icon.svg` 及生成的 PNG/ICNS 已使用确认的折角版助手图标；构建命令使用 `--no-sign`，没有签名、公证或真实分发验收。

### 应用图标

`app-icon.svg` 是统一图标源，包含已确认的原图和圆角透明裁切。`src-tauri/icons/icon.icns` 用于 Finder/Dock，`src-tauri/icons/icon.png` 用于菜单栏；两者应从同一源生成。在 `desktop/` 执行：

```bash
icon_stage="$(mktemp -d /private/tmp/openbot-icons.XXXXXX)"
npm run tauri -- icon app-icon.svg --output "$icon_stage"
cp "$icon_stage/icon.png" src-tauri/icons/icon.png
cp "$icon_stage/icon.icns" src-tauri/icons/icon.icns
```

CLI 默认生成的其他平台图标保留在临时目录，不纳入本项目。更新图标后，需要执行上节的 Tauri 构建命令并重新启动新应用；既有 `.app` 的图标不会随源文件变化自动更新。

### 原生服务启动与生命周期

原生层只启动资源内固定 `runtime/bin/python3 -I -B service_entry.py`，传入系统应用数据目录、独立随机 ready 文件和固定 runtime 目录。不会连接固定 8000 端口或寻找宿主 Python。每次启动创建独立的 256-bit 实例 ID 和 token；启动 Python 服务时 token 仅通过子进程环境传递，不写入 ready 文件或服务命令行。

子进程清空父环境，仅保留 HOME、TMPDIR、LANG、LC_CTYPE，使用随包 bin 加系统目录的固定 PATH；显式配置 `PYTHON_DOTENV_DISABLED=1` 和随包 tokenizer 缓存。服务凭据由 Python 从应用自己的配置读取，不继承父 shell 中的服务密钥。stdout/stderr 追加到应用数据目录 `logs/desktop-service.log`（0600）。

Python 监听 literal 127.0.0.1 的随机端口、API ready 后，以 0600 原子写入 `{protocol_version:1,instance_id,pid,port}`。Rust 拒绝符号链接、不安全权限、超限/非法 JSON、非本次 ID/PID、错误协议或零端口。校验后才返回连接信息；45 秒未就绪或进程异常退出显示 failed。仅退出码 75 表示明确配置重启，自动轮换 ID/token 再启动；其它退出不自动重试，也不重放业务请求。

主窗口关闭时隐藏，托盘提供真实状态、重新打开与退出；Dock 重开也恢复窗口。明确退出通过自己持有的 Child stdin 发送精确 `shutdown\n` 并关闭 stdin，最多等 10 秒；超时只 kill/reap 自己启动的 Child，不按端口或 PID 搜索/终止其它服务。单实例插件负责恢复已有窗口，应用数据目录的 flock 另防启动竞争导致双服务。

| 原生命令 | 返回值与范围 |
| --- | --- |
| `desktop_connection()` | `{status:'starting'|'ready'|'failed', baseUrl?, instanceId?, token?, error?}`；仅 ready 包含已校验连接；instanceId 随每次重启轮换，可用于只读恢复绑定；token 不持久化。 |
| `desktop_open_web()` | 仅从 ready 快照构造本实例回环 Web 控制台地址，用固定 `/usr/bin/open` 打开；不接受前端 URL/path 参数。 |
| `desktop_retry()` | 仅失败且已停止的本实例可重试；成功返回 null，重复启动报错。 |
| `desktop_quit()` | 请求有序停止后退出应用。 |
| `desktop_autostart()` | 返回系统登录启动的实际布尔状态。 |
| `desktop_set_autostart({enabled})` | 修改登录启动并返回实际状态；首次启动不会自动开启。 |
| `desktop_choose_directory()` | 系统单选文件夹，返回绝对路径；取消返回 null，不接受任意命令。 |

浏览器控制台入口将当前 token 放入 URL 片段；前端捕获后立即清除片段，经受保护接口校验，只在当前页面内存保存凭据。HTTP 使用同源 Bearer，原 WebSocket 通过请求子协议 `openbot.auth.<token>` 认证，不在 URL 查询参数中携带凭据。服务不设置或接受认证 cookie，避免共享回环宿主的跨端口 cookie 泄露；刷新或服务重启后需要从应用重新打开。原生命令不记录 URL/token，不接受外部地址；实际浏览器流程仍需 UI 验收。

登录启动使用官方 autostart 插件 LaunchAgent，加 `--background` 隐藏主窗口；未授权时不注册。目录选择只通过受限原生命令开放，窗口没有任意 filesystem/shell 插件权限。CSP 仅增加动态回环 HTTP/WebSocket 连接，不放开任意外部 connect 目标。

资源映射包括 `service_entry.py`、离线探测脚本/源 JSON、runtime 和同次构建的 `frontend/dist/`。前端同时嵌入 WebView，并复制一份到 `Resources/frontend/`，供 Python 本机 HTTP 控制台使用；因此增加一份静态产物体积，不分开构建两套前端。不复制开发 src、probe 缓存或用户数据。2026-10-30 当前原生实现通过 cargo fmt/check 及 12 项 Rust 单测：握手校验、单实例 lease、有序关闭、超时仅清理自有 Child、启动截止时间、错误握手、异常退出、75 重启轮换身份、显式重试、父环境密钥隔离及受限 Web 控制台 URL 构造。状态/清理单测使用合成 shell 进程，不读取真实账号。完整真实服务、原生界面、登录项系统行为、目录选择、最低 macOS、签名后原生库加载与干净机器行为仍需各自验收。

## 下载量评估

2026-10-29 官方 PBS 20261026 的 CPython3.12.16 arm64 stripped 包为 25,035,343 字节（23.88 MiB）；当前 uv.lock 的 84 个生产 wheel 压缩总量 68,986,842 字节（65.79 MiB），本机标签未遇到必须 sdist 构建的项。另有官方 rg 归档 1,764,284 字节和真实 tokenizer 资源。最低系统版本需重新匹配和实测；下载量不等于展开目录或最终安装包体积。

## 外置完整服务 smoke（仅假模型）

在仓库根目录执行：

```bash
.venv/bin/python -I -B desktop/probe/service_probe.py \
  --app "/private/tmp/openbot-desktop-target/aarch64-apple-darwin/debug/bundle/macos/OpenBot.app"
```

Controller 在 60 秒外层超时内，用 `.app` 内解释器与源码启动真实 `src.application.Application`。工作目录与 config.yaml、SQLite/JSONL/档案等均位于专用 TemporaryDirectory；模型只有本机 127.0.0.1 临时 fake OpenAI endpoint 和虚构 key，渠道、embedding、reranker、OTLP 明确关闭。真实 /health 与 REST /api/chat 必须成功，消息必须持久化，然后 API、scheduler 和数据库有序关闭。structlog error/critical、标准 ERROR:/CRITICAL:、Traceback 和 parse_failed 标记行都会使 smoke 失败；unexpected_error_logs 统计实际匹配行数，不能仅凭 HTTP 200 判定通过。

子进程在核心 import 前设置 PYTHON_DOTENV_DISABLED=1，并验证随包 python-dotenv 1.2.2 确实在 find_dotenv 之前短路；额外拒绝 dotenv 搜索和任何 .env 文件读取，拒绝临时目录外 config.yaml，以及 connect/bind/sendto/getaddrinfo 事件中非 literal-loopback 的 IP 目标（只接受 127.0.0.1 和 ::1 的 str/bytes 值）。这只是本诊断的有限 CPython audit 护栏，不是进程沙箱。Application 默认会扫描全局 skills，为避免读取用户文件，诊断进程内将 Path.home() 临时指向合成空 home，不改 HOME 环境或生产实现。该设置只模拟干净用户 profile，与正式原生启动器的数据路径验证分开。

2026-10-29 实际结果：health 200、REST 200、回复与合成模型一致、2 条消息持久化、4 次本机 fake 模型调用、数据库关闭与后台任务清理成功，应用错误日志 0。护栏及日志分类单测 25 项通过；desktop 全部单测共 38 项通过。受默认沙箱限制时监听本地 socket 可能被拒绝，需在允许本机临时监听的环境运行。

这些脚本是外置 CLI 诊断，没有加入原生命令。其结果不是外部真实模型、真实渠道、正式原生服务 launcher、签名分发或干净 Mac 验收；正式服务与界面接入的检查应另记录。

## 桌面配置与导入操作

首次启动可以填写主模型及默认目录，或先导入旧部署。模型保存后服务会重启；工作目录不搬动应用数据。设置中的“渠道与服务”可配置备用/路由模型、Telegram、飞书、微信、embedding/reranker 和凭据。空密码框保留已保存值，勾选清除并保存才删除；有执行或排队任务时不能保存重启。保存不表示外部连通验证成功。

微信先保持渠道关闭，在“微信扫码登录”获取二维码并用微信确认，再启用渠道并保存重启。更换账号前先关闭渠道并保存。登录失败或取消不替换旧账号；如果确认先于取消，界面会如实显示登录信息已保存。

导入只在首次配置前可用，不覆盖或合并已有业务数据：

1. 正常退出旧 OpenBot，保持源目录不再写入。
2. 选择包含 `config.yaml` 和 `data/` 的旧部署目录，确认源已停止，预览文件清单。
3. 确认复制；服务暂存并校验后重启，界面显示最终结果。
4. 确认配置后逐项启用渠道和定时任务，重新授权需要的执行工具。

当前仅支持 schema 11、`data/openbot.db` 与 `data/wechat/ilink_state.json` 标准路径，最多 20000 文件、2 GiB。非空 WAL、源被占用、链接、特殊文件或目标冲突会拒绝导入；不会替用户修改源数据库。复制数据库、历史 JSONL、个人 Markdown、技能、快照和微信状态；所选 `.env` 仅迁移业务凭据，不加载其它环境变量。源码、工作目录、日志和缓存不复制。原源目录与发布前的目标备份保留，失败数据不会被永久删除。

隔离 Demo 的设置页可模拟服务、扫码、导入及更新；`/desktop-demo/manage/settings?preview=import` 展示首次导入流程，所有修改仅在内存中。

## 整包工作流诊断

从仓库根目录执行。第二条工作流诊断设置 60 秒外层超时，只创建并回收本次合成进程：

```bash
.venv/bin/python -I -B desktop/probe/desktop_service_probe.py \
  --app "/private/tmp/openbot-desktop-target/aarch64-apple-darwin/debug/bundle/macos/OpenBot.app"
.venv/bin/python -I -B desktop/probe/desktop_workflows_probe.py \
  --app "/private/tmp/openbot-desktop-target/aarch64-apple-darwin/debug/bundle/macos/OpenBot.app" \
  --report /private/tmp/openbot-desktop-workflows.json
```

前者验证真实桌面 entry 的首配、重启、HTTP/WS 认证及续聊；后者额外验证真实 lsof、源哈希不变、离线导入/任务暂停、配置和密钥重启后生效，以及更新忙碌拒绝、关门和租约恢复。模型仅为 literal-loopback fake，不读取旧部署或真实凭据。2026-10-30 后者在新包中通过，错误日志 0；报告不代表真实外部账号或更新安装已验收。

## 更新与发行准备

原生更新检查读取构建时固定的 `OPENBOT_UPDATE_ENDPOINT` 和 `OPENBOT_UPDATE_PUBLIC_KEY`；缺失即显示未配置。用户点击安装后下载并校验签名及目标版本，安装前再次检查全部入口是否空闲，并等待自有 Python 自然退出。下载/忙碌失败保留运行服务；安装失败仅在旧包文件、链接和权限指纹一致时恢复服务，无法确认则保持停止并提示重新安装签名应用。

`desktop/scripts/release_prepare.py --help` 说明生成发行配置/构建计划的参数：实际 HTTPS 更新地址、Tauri signer 生成的公开 `.pub`、Developer ID Application 身份、已验收最低 macOS 版本和新的输出目录。它检查 Tauri、Cargo、前端、桌面工程及 Python 的版本一致性，不自动升级版本或签名。构建前将计划中的公开 `compile_environment` 用于本次编译，并在构建机配置更新私钥和 Apple 公证凭据；不把秘密写进配置文件或提交。

`desktop/scripts/release_manifest.py --help` 从 `.app.tar.gz` 与对应签名生成本地 metadata；签名须以 `tauri signer sign --app-version` 绑定目标版本。该脚本仅检查格式与版本绑定，不冒充密码学验签，也不上传文件。真实安装仍由应用用固定公钥验签。更新服务托管、Apple 签名公证、两版本整包升级、失败恢复及干净机器测试尚未完成。

用户已选择 GitHub Releases；仓库及资产约定见 `github-release.example.json`。候选更新入口为 `https://github.com/yutaoshao/openbot/releases/latest/download/latest.json`，稳定 Release 需要包含该 metadata、同版本 `.app.tar.gz` 及签名。此示例尚未上传，也没有启用当前应用的更新服务。Apple Developer ID 和公证配置准备好后，再生成正式发行计划并验收；私钥由发行者单独保管。

若开发机上的 Tauri DMG 脚本因 Finder 占用临时卷而失败，可用系统 `hdiutil` 在新的临时目录中只放本次 `OpenBot.app` 与 `/Applications` 链接，执行 `hdiutil create -srcfolder <组装目录> -format UDZO <新输出.dmg>`，再执行 `hdiutil verify <新输出.dmg>`。不覆盖既有文件，不强制卸载其它卷。这种无 Finder 布局的开发映像仍未签名或公证，不能替代正式发行验收。
