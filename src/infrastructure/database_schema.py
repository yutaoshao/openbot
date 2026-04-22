"""Static schema definitions for the SQLite storage layer."""

from __future__ import annotations

SCHEMA_SQL = """\
-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL,
    applied_at TEXT NOT NULL
);

-- Conversations
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '{single_user_id}',
    title TEXT,
    summary TEXT,
    platform TEXT NOT NULL DEFAULT 'unknown',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Messages
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    model TEXT,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    latency_ms INTEGER DEFAULT 0,
    tool_calls TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
    ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_created_at
    ON messages(created_at);

-- Knowledge
CREATE TABLE IF NOT EXISTS knowledge (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '{single_user_id}',
    source_conversation_id TEXT,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT,
    priority TEXT NOT NULL DEFAULT 'P1',
    confidence REAL DEFAULT 1.0,
    access_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_knowledge_category
    ON knowledge(category);
CREATE INDEX IF NOT EXISTS idx_knowledge_priority
    ON knowledge(priority);
CREATE INDEX IF NOT EXISTS idx_knowledge_expires_at
    ON knowledge(expires_at);

-- Preferences
CREATE TABLE IF NOT EXISTS preferences (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '{single_user_id}',
    category TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    evidence TEXT,
    confidence REAL DEFAULT 0.5,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, category, key)
);

CREATE INDEX IF NOT EXISTS idx_preferences_category
    ON preferences(category);
-- User identities
CREATE TABLE IF NOT EXISTS user_identities (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    platform_user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(platform, platform_user_id)
);

CREATE INDEX IF NOT EXISTS idx_user_identities_user_id
    ON user_identities(user_id);

-- Metrics
CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_name TEXT NOT NULL,
    data TEXT NOT NULL,
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_metrics_event_name
    ON metrics(event_name);
CREATE INDEX IF NOT EXISTS idx_metrics_timestamp
    ON metrics(timestamp);

-- Logs (AgentTrace three-surface structured logs)
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    level TEXT NOT NULL,
    event TEXT NOT NULL,
    surface TEXT,
    trace_id TEXT,
    interaction_id TEXT,
    platform TEXT,
    iteration INTEGER,
    data TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_logs_trace_id ON logs(trace_id);
CREATE INDEX IF NOT EXISTS idx_logs_interaction_id ON logs(interaction_id);
CREATE INDEX IF NOT EXISTS idx_logs_event ON logs(event);
CREATE INDEX IF NOT EXISTS idx_logs_surface ON logs(surface);
CREATE INDEX IF NOT EXISTS idx_logs_level ON logs(level);

-- Schedules
CREATE TABLE IF NOT EXISTS schedules (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    prompt TEXT NOT NULL,
    cron TEXT NOT NULL,
    target_platform TEXT,
    target_id TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    last_run_at TEXT,
    next_run_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_schedules_status
    ON schedules(status);
CREATE INDEX IF NOT EXISTS idx_schedules_next_run_at
    ON schedules(next_run_at);
"""

VEC_TABLES_SQL = """\
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_embeddings USING vec0(
    knowledge_id TEXT PRIMARY KEY,
    embedding float[{dimensions}]
);

CREATE VIRTUAL TABLE IF NOT EXISTS conversation_embeddings USING vec0(
    conversation_id TEXT PRIMARY KEY,
    embedding float[{dimensions}]
);
"""
