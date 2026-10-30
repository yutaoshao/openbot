# 随包运行时构建目录

除本说明外，目录内容均为忽略的生成产物，不进入 Git。使用 `desktop/scripts/assemble_runtime.py` 从固定 SHA256 的官方独立 Python/rg 及 uv.lock 的生产依赖装配；不复制开发虚拟环境或宿主 Python 链接冒充独立运行时。

固定契约：`bin/python3`、`bin/rg`、`tokenizer-cache/`、`app/src/`、`requirements.lock.txt` 和 `build-manifest.json`。启动使用 `-I -B`，真实 tokenizer 缓存必须在核心模块 import 前配置；源码快照只含 `.py`。保留 Python、rg、wheels 的许可证和元数据。

2026-10-29 已装配 CPython 3.12.16、84 个生产依赖、rg 15.2.0 及真实 cl100k/o200k 缓存，离线探测通过。签名后原生库、干净机器执行、完整应用服务及渠道流程仍需另行验收，不能凭本目录存在宣称首版已可分发。
