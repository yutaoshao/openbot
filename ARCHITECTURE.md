# How OpenBot handles a message

OpenBot runs one local user across its configured channels. `Application`
constructs the model gateway, storage, tools, memory services, channel adapters,
and Agent. Startup owns their resource order; shutdown stops new channel and API
work, cancels and waits for background memory jobs, then closes the database.

```text
Telegram / Feishu / WeChat / WebSocket / REST
  -> normalized message + local user identity
  -> serialized user turn
  -> Agent: prompt -> model/tool rounds -> verify outcome
  -> persist assistant turn -> send reply -> confirm actual delivery
  -> background compression and online memory sync
```

Channel adapters normalize incoming messages and present outgoing responses.
`MsgHub` and `src/application/message_dispatch.py` route channel messages through
`UserExecutionCoordinator`. REST chat uses the same Agent contract and user
serialization. `Agent.run()` and `run_stream()` share a single turn execution;
the turn owns its mutable counters, selected tools and verification state.
Tools return structured results and effects. A claimed file change or other
required effect is checked before a completed outcome can be reported. The
reply is confirmed only after its channel reports delivery.

`PromptBuilder` assembles context. `SharedTimelineMemory` restores complete
turns from stored messages, summarizes older turns and saves the summary with
its source boundary before dropping raw history. `PersonalHistory` ranks
original user messages, expands adjacent messages and related later events,
and labels assistant messages as context. `HistorySources` reads archived JSONL
and SQLite rows off the message event loop. Markdown dossiers under
`data/personal_memory/` are the editable authority for personal facts and
events; writes check the document revision and preserve manual edits.

After a successful turn, `PostTurnMemory` owns the background task until
shutdown. `OnlineMemorySync` selects complete, eligible turns, serializes
extraction and advances its cursor only after each successful turn. The offline
history backfill uses separate tables and progress through
`PersonalBackfillRepo`; it never runs as part of ordinary message processing.
See [advanced operations](ADVANCED.md) for its review and apply commands.

Source reading route: `src/application/container.py` and `lifecycle.py` for
assembly; `message_dispatch.py` for channel routing; `src/agent/agent.py` and
`src/agent/runtime/` for a turn; `src/agent/conversation/` for context and
online memory; `src/memory/personal_backfill.py` and
`src/infrastructure/storage/` for offline processing and source storage.
