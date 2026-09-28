# 进阶操作

### 个人档案与上下文

个人事实、宠物、健康与重要经历保存在本地 `data/personal_memory/`；
`INDEX.md` 是主题导航，每个主题分为已确认事实、事件经过、推测、待核实信息。
可以直接编辑 Markdown，也可以在管理面板的「记忆 → 个人档案」编辑；
网页保存会检测文档被其他编辑器修改的冲突。档案记有用户原话的归档行或
数据库消息 ID，便于沿历史核对先前的理由和后续。旧的知识库用于一般知识，
旧的个人资料副本仅作历史线索。

四层记忆继续协作：工作记忆保存近期对话；情景记忆帮助定位旧会话并回读原话；
语义记忆保存一般知识；程序性记忆读取档案中的通用和场景偏好。
个人档案同时提供当前事实和事件脉络，不再另写一份个人知识或偏好作为权威。
档案检索结合关键词、已配置的向量服务和精排；手动编辑后，下次读取采用新版本。
相关历史按来源和事件阶段补查；材料过长时会说明还有未展开的原文，不能据此判断事情没有后续。
明确计划或正在经历的事情可以在相关话题中自然追问；先检查已有后续，
答复实际交付后才记录“已问”，没有新回复时不会反复催问。普通咨询不自动变成待办。

升级旧数据库后，旧知识先标为待核查，不参与一般知识注入。以下命令保留原文，
按类型分类并恢复一般知识检索；需使用已配置的模型服务，失败可重复运行以续作。
旧偏好必须核对用户原话后才迁入档案，不能直接复制旧模型总结。

```bash
uv run python -m src.memory.maintenance audit-legacy
uv run python -m src.memory.maintenance rebuild
```

分类报告、迁移备份和处理进度均保存在本地；重建命令只重建档案检索索引，
不会用旧数据库内容覆盖 Markdown。

补齐已有聊天时，先备份 `data/openbot.db` 与 `data/personal_memory/`，再运行：

```bash
uv run python -m scripts.backfill_personal_memory inventory
uv run python -m scripts.backfill_personal_memory stage
uv run python -m scripts.backfill_personal_memory apply
uv run python -m src.memory.maintenance rebuild
```

`stage` 逐条核对数据库与聊天归档，记录待合并、无新增、待核实和失败状态；
先检查本地 `data/personal_memory/_migration/completeness-review.jsonl` 中的
原话和候选；主体归属含糊的条目另列入 `completeness-uncertain.jsonl`，
不会自动合并。核对后再执行 `apply`。失败后重复运行 `stage` 会重试失败项，完成状态
不会重复写入。该进度与新对话的增量进度分开保存。已有旧的首次精选档案
保留在原位置，回扫只补充有来源的内容。同一人物或项目有多种称呼时，可在本地
`data/personal_memory/_migration/subject_aliases.json` 配置归档名称和别名映射；
这份含个人信息的配置不会进入 Git。

本示例把 `model.primary.context_window` 总窗口设为 **272000**，
`max_tokens: 16384` 预留输出；`agent.input_token_budget` 默认 **255616**。
达到有效输入预算的 `compression_trigger_ratio: 0.9`（约230054）时压缩较早轮次，
`recent_token_budget: 128000` 控制近期原文保留目标。系统提示、档案、工具定义
和工具返回均计入完整输入。备用模型及启用的路由模型应分别配置其总窗口。
首次加载较长的旧聊天时，系统分段生成并保存摘要；重启后从摘要边界恢复完整轮次。

填写 `context_window` 表示维护者确认这条模型服务可接受该总窗口，
它也可以是低于服务实际能力的本地使用上限。计数接口可用时优先精确计数；
返回404时允许使用本地tokenizer估算，保留15%估算余量和固定请求开销，
不会仅因计数接口缺失而退回128k。只有未填写总窗口时才采用128000输入限制。
响应usage继续核验估算误差；超过有效预算明确报错，不静默截断。
这里的272000是输入与输出的总预算，不代表价格分界。

本地后端开发时，可以使用自动重启脚本：

```bash
cp scripts/openbot-watch.example.sh scripts/openbot-watch.sh
chmod +x scripts/openbot-watch.sh
scripts/openbot-watch.sh
```

watcher 会在 `main.py`、源码、`.env`、`config.yaml`、`pyproject.toml` 或 `uv.lock` 变化时重启 `main.py`。它会忽略 `data/`，避免日志或运行时写入导致循环重启。
