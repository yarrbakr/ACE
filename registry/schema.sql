-- ACE Public Registry schema — agent discovery service.
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS registered_agents (
    aid             TEXT PRIMARY KEY,
    agent_card      TEXT NOT NULL,
    name            TEXT NOT NULL DEFAULT '',
    description     TEXT NOT NULL DEFAULT '',
    url             TEXT NOT NULL DEFAULT '',
    registered_at   TEXT NOT NULL DEFAULT (datetime('now')),
    last_heartbeat  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS registry_capabilities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    aid             TEXT NOT NULL REFERENCES registered_agents(aid) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    price           INTEGER NOT NULL DEFAULT 0,
    tags            TEXT NOT NULL DEFAULT '',
    UNIQUE(aid, name)
);

CREATE INDEX IF NOT EXISTS idx_reg_cap_name ON registry_capabilities(name);
CREATE INDEX IF NOT EXISTS idx_reg_cap_price ON registry_capabilities(price);
CREATE INDEX IF NOT EXISTS idx_reg_agents_heartbeat ON registered_agents(last_heartbeat);
