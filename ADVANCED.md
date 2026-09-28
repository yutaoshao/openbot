# Advanced operations

### Personal memory and context

Personal facts, pets, health, and important experiences live locally in
`data/personal_memory/`. `INDEX.md` links to editable topic dossiers with
confirmed facts, events, inferences, and unresolved items. Edit the Markdown
directly or use the dashboard Memory → Personal dossiers editor, which checks
the document revision before saving. Sources refer to original conversation
lines or database message IDs. The knowledge base remains for general knowledge.

The four memory responsibilities remain: working memory keeps recent turns;
episodic memory locates past conversations and their original speech; semantic
memory stores general knowledge; procedural memory reads confirmed global and
scoped preferences from the dossiers. Personal information has one authority.
Dossier retrieval combines keywords, configured embeddings, and the existing
reranker, then reads the current Markdown revision. Relevant unresolved plans
may receive a natural follow-up after checking subsequent history. A question
is marked asked only after successful transport; ordinary advice requests do
not become tasks, and unanswered follow-ups are not repeated.
When related original history is lengthy, the answer context notes that more
source messages remain searchable rather than treating them as absent.

After a database upgrade, old knowledge is explicitly unreviewed and excluded
from general recall until classified. These resumable commands preserve its
text and rebuild the disposable dossier index using configured model services:

```bash
uv run python -m src.memory.maintenance audit-legacy
uv run python -m src.memory.maintenance rebuild
```

Reports and backups remain local. Old generated preferences require original
user evidence before migration into dossiers. Index rebuilding never overwrites
Markdown from an older database copy.

To process existing chats, back up `data/openbot.db` and `data/personal_memory/`,
then run `uv run python -m scripts.backfill_personal_memory inventory`, followed by
`stage`. Review the local candidate and source report at
`data/personal_memory/_migration/completeness-review.jsonl` before running `apply`.
Ambiguous subjects appear separately in `completeness-uncertain.jsonl` and are not merged.
Run `uv run python -m src.memory.maintenance rebuild` afterward. Failed stages
can be retried; progress is independent of new conversation processing.
Local name mappings for people and projects can be edited in
`data/personal_memory/_migration/subject_aliases.json`; this private file is
excluded from Git.

The example sets `model.primary.context_window` to **272,000 total tokens**
and reserves **16,384** for output via `max_tokens`. The default
`agent.input_token_budget` is **255,616**; compression begins at 90% of the
effective input limit (about 230,054), retaining a 128,000-token recent transcript
target. System prompts, dossiers, tool definitions, and results count toward input.
Configure fallback and enabled routing providers separately.
The first load of a long chat history saves summaries in segments; restarts
resume at the saved boundary with complete recent turns.

A configured `context_window` is the operator-confirmed service window or a
smaller local total budget. Exact counting is preferred when available. If the
counting endpoint returns 404, local tokenization with a 15% margin and fixed
request overhead is allowed at the configured window. Missing exact counting
alone does not impose a 128k cap; that cap applies only when no window is set.
Response usage audits estimation error. Requests over budget fail explicitly
without silent truncation. This total budget is not a pricing threshold.

For backend development with automatic restarts:

```bash
cp scripts/openbot-watch.example.sh scripts/openbot-watch.sh
chmod +x scripts/openbot-watch.sh && scripts/openbot-watch.sh
```

The watcher restarts `main.py` when source files, `.env`, `config.yaml`,
`pyproject.toml`, or `uv.lock` change. It ignores `data/` to avoid restart loops
from log or runtime writes.
