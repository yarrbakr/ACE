-- ACE SQLite schema — double-entry ledger, escrow, capabilities, transactions
-- Designed for WAL mode with proper constraints, FKs, and indexes.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ─── Agents ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS agents (
    aid             TEXT PRIMARY KEY,                        -- Agent ID (derived from public key)
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    public_key      TEXT NOT NULL UNIQUE,                    -- Hex-encoded Ed25519 public key
    endpoint_url    TEXT,                                    -- HTTP endpoint for this agent
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ─── Accounts (balances) ───────────────────────────────────────────────────
-- NOTE: No FK to agents — system accounts (SYSTEM:ISSUANCE, etc.) are not agents.
-- No CHECK (balance >= 0) — SYSTEM:ISSUANCE goes negative to track money supply.

CREATE TABLE IF NOT EXISTS accounts (
    aid             TEXT PRIMARY KEY,
    balance         INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ─── System accounts (seeded on schema creation) ─────────────────────────
-- ISSUANCE: source of minted currency (goes negative = total money supply).
-- ESCROW: holds locked funds during trades. BURN: destroyed currency. FEES: platform fees.

INSERT OR IGNORE INTO accounts (aid, balance) VALUES ('SYSTEM:ISSUANCE', 0);
INSERT OR IGNORE INTO accounts (aid, balance) VALUES ('SYSTEM:ESCROW', 0);
INSERT OR IGNORE INTO accounts (aid, balance) VALUES ('SYSTEM:BURN', 0);
INSERT OR IGNORE INTO accounts (aid, balance) VALUES ('SYSTEM:FEES', 0);

-- ─── Ledger entries (double-entry bookkeeping) ─────────────────────────────
-- Each transfer creates TWO entries: one DEBIT (sender) and one CREDIT (receiver).
-- The invariant: sum of all DEBIT amounts == sum of all CREDIT amounts.

CREATE TABLE IF NOT EXISTS ledger_entries (
    entry_id        TEXT PRIMARY KEY,
    transaction_id  TEXT NOT NULL,
    timestamp       TEXT NOT NULL DEFAULT (datetime('now')),
    account         TEXT NOT NULL REFERENCES accounts(aid),
    direction       TEXT NOT NULL CHECK (direction IN ('DEBIT', 'CREDIT')),
    amount          INTEGER NOT NULL CHECK (amount > 0),
    balance_after   INTEGER NOT NULL,
    entry_type      TEXT NOT NULL CHECK (entry_type IN (
        'ISSUANCE', 'TRANSFER', 'FEE', 'BURN',
        'ESCROW_LOCK', 'ESCROW_RELEASE', 'ESCROW_REFUND'
    )),
    description     TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_ledger_account     ON ledger_entries(account, timestamp);
CREATE INDEX IF NOT EXISTS idx_ledger_transaction ON ledger_entries(transaction_id);

-- ─── Escrows ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS escrows (
    escrow_id       TEXT PRIMARY KEY,
    buyer_aid       TEXT NOT NULL REFERENCES accounts(aid),
    seller_aid      TEXT NOT NULL REFERENCES accounts(aid),
    amount          INTEGER NOT NULL CHECK (amount > 0),
    state           TEXT NOT NULL DEFAULT 'LOCKED'
                    CHECK (state IN ('LOCKED', 'RELEASED', 'REFUNDED')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    timeout_at      TEXT NOT NULL,
    released_at     TEXT,
    CHECK (buyer_aid != seller_aid)
);

CREATE INDEX IF NOT EXISTS idx_escrow_state_timeout ON escrows(state, timeout_at);

-- ─── Capabilities (skills an agent offers) ─────────────────────────────────

CREATE TABLE IF NOT EXISTS capabilities (
    id              TEXT PRIMARY KEY,                        -- UUID
    aid             TEXT NOT NULL REFERENCES agents(aid) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    price           INTEGER NOT NULL CHECK (price >= 0),     -- cost in tokens
    tags            TEXT NOT NULL DEFAULT '[]',               -- JSON array of tags
    version         TEXT NOT NULL DEFAULT '1.0.0',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(aid, name, version)
);

CREATE INDEX IF NOT EXISTS idx_capabilities_aid  ON capabilities(aid);
CREATE INDEX IF NOT EXISTS idx_capabilities_name ON capabilities(name);

-- ─── Transactions (8-state capability trade lifecycle) ──────────────────────

CREATE TABLE IF NOT EXISTS transactions (
    tx_id           TEXT PRIMARY KEY,
    state           TEXT NOT NULL DEFAULT 'INITIATED' CHECK (state IN (
        'INITIATED', 'QUOTED', 'FUNDED', 'EXECUTING',
        'VERIFYING', 'SETTLED', 'DISPUTED', 'REFUNDED'
    )),
    buyer_aid       TEXT NOT NULL,
    seller_aid      TEXT NOT NULL,
    capability_id   TEXT NOT NULL,
    price           INTEGER NOT NULL DEFAULT 0,
    escrow_id       TEXT,
    result_hash     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    timeout_at      TEXT NOT NULL,
    CHECK (buyer_aid != seller_aid)
);

CREATE INDEX IF NOT EXISTS idx_tx_state   ON transactions(state);
CREATE INDEX IF NOT EXISTS idx_tx_buyer   ON transactions(buyer_aid);
CREATE INDEX IF NOT EXISTS idx_tx_seller  ON transactions(seller_aid);
CREATE INDEX IF NOT EXISTS idx_tx_timeout ON transactions(state, timeout_at);

-- ─── Transaction history (immutable audit trail) ────────────────────────────

CREATE TABLE IF NOT EXISTS transaction_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tx_id           TEXT NOT NULL REFERENCES transactions(tx_id),
    from_state      TEXT,
    to_state        TEXT NOT NULL,
    actor_aid       TEXT,
    timestamp       TEXT NOT NULL DEFAULT (datetime('now')),
    note            TEXT
);

CREATE INDEX IF NOT EXISTS idx_tx_history ON transaction_history(tx_id, timestamp);
