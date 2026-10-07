# 一条消息如何经过 OpenBot

OpenBot 在已配置的消息平台之间服务同一个本地用户。`Application` 构造模型网关、
存储、工具、记忆服务、消息适配器和 Agent。启动过程负责资源的启动顺序；停机时先停止
接收新消息，再取消并等待后台记忆任务，最后关闭数据库。

```text
Telegram / 飞书 / 微信 / WebSocket / REST
  -> 标准消息与本地用户身份
  -> 同一用户的轮次串行执行
  -> Agent：组装上下文 -> 模型与工具循环 -> 验证结果
  -> 保存助手回合 -> 发送回复 -> 确认实际交付
  -> 后台压缩与在线记忆同步
```

消息适配器转换平台格式，`MsgHub` 与 `src/application/message_dispatch.py` 将
消息交给 `UserExecutionCoordinator`。REST 聊天使用相同的 Agent 接口和用户串行
规则。`Agent.run()` 与 `run_stream()` 共用一套单轮执行流程；单轮对象管理工具、计数
和结果验证。工具返回结构化效果：文件是否实际修改等要求在宣告完成前核实。平台实际
交付回复后，才确认需要交付的后续事项。

`PromptBuilder` 负责组装上下文。`SharedTimelineMemory` 从已存消息恢复完整轮次，
压缩旧轮次时先保存摘要和真实消息边界，再裁剪内存历史。`PersonalHistory` 匹配用户
原话，补充相邻消息和相关事件的后续；助手消息明确标为语境。`HistorySources` 在
消息事件循环之外读取 JSONL 归档与 SQLite。`data/personal_memory/` 下的 Markdown
档案是个人事实与事件的可编辑权威；写入时检查文档版本，保护人工编辑。

个人档案的检索索引按段落生成；`PromptBuilder` 使用命中的段落和有界上下文，保留来源字段以便
追溯，但不会因为命中一个主题就把整个主题文档注入模型。Responses provider 会把内部保存的
chat-completions 风格工具调用历史转换为 Responses API 的 `function_call` 和
`function_call_output` 输入项。

成功回合结束后，`PostTurnMemory` 持有后台任务直至停机。`OnlineMemorySync` 只处理
符合条件的完整轮次，串行提取，并在每轮成功后推进游标。离线历史回扫通过
`PersonalBackfillRepo` 使用独立进度，不会随普通消息自动运行。回扫盘点、核对与写入
命令见[进阶操作](ADVANCED_CN.md)。

阅读源码可以依次看：`src/application/container.py` 与 `lifecycle.py`（资源组装），
`message_dispatch.py`（消息入口），`src/agent/agent.py` 与 `src/agent/runtime/`
（单轮执行），`src/agent/conversation/`（上下文和在线同步），最后是
`src/memory/personal_backfill.py` 与 `src/infrastructure/storage/`（离线处理和来源读取）。
