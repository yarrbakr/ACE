# Architecture

## Module Structure

```
src/ace/
  core/          <- Pure business logic (no framework dependencies)
    config.py        Settings (Pydantic), config file management
    identity.py      Ed25519 keypair, AID derivation, sign/verify
    ledger.py        Double-entry bookkeeping, mint, transfer
    escrow.py        Lock/release/refund with atomic state transitions
    capability.py    SKILL.md parser, Agent Card, capability registry
    transaction.py   8-state transaction engine, timeout monitor
    schema.sql       SQLite schema for all tables

  cli/           <- Typer CLI adapter (thin shell over core)
    main.py          App entry point, command registration
    commands/        One file per command group

  api/           <- FastAPI adapter (thin shell over core)
    server.py        App factory, lifespan, route mounting
    middleware.py    Ed25519 signature verification
    deps.py          Dependency injection (Depends)
    routes/          One file per route group

  discovery/     <- Pluggable discovery (port/adapter pattern)
    base.py              DiscoveryAdapter ABC
    centralized.py       Local SQLite-backed discovery
    gossip.py            Peer-to-peer gossip protocol
    public_registry.py   HTTP client for public registry
```

## Dependency Rule

Dependencies flow **inward only**:

```
cli/ ──> core/ <── api/
              ^
              |
         discovery/
```

`core/` has zero framework dependencies. `cli/` and `api/` are thin adapters that call core methods.

## Key Design Patterns

### Double-Entry Bookkeeping

Every token transfer creates exactly 2 ledger entries (DEBIT + CREDIT). The sum of all debits always equals the sum of all credits. System accounts track the money supply.

### Escrow

Funds are locked in a system escrow account before work begins. State transitions use `UPDATE ... WHERE state = 'LOCKED'` with rowcount checking for atomicity -- prevents double-release/refund.

### 8-State Transaction Engine

```
INITIATED -> QUOTED -> FUNDED -> EXECUTING -> VERIFYING -> SETTLED
                                                        -> DISPUTED -> SETTLED
                                                                    -> REFUNDED
```

All state changes flow through a single `_transition()` choke point that validates legality, checks authorization, and logs to an append-only audit trail.

### Discovery Adapters

Discovery is pluggable via the `DiscoveryAdapter` ABC:

| Mode | Class | Description |
|------|-------|-------------|
| `centralized` | `CentralizedDiscovery` | Local SQLite registry |
| `gossip` | `GossipDiscovery` | Peer-to-peer gossip protocol |
| `registry` | `PublicRegistryDiscovery` | HTTP client for public registry |

### App Factory

`create_app(settings, identity)` returns a configured FastAPI instance. No global app variable. The lifespan pattern initializes all dependencies on startup and cleans up on shutdown.

## Data Flow: A Transaction

```
1. Buyer POSTs to /transactions         (INITIATED)
2. Seller submits quote                  (QUOTED)
3. Buyer accepts, funds locked in escrow (FUNDED)
4. Seller executes work                  (EXECUTING)
5. Seller delivers result hash           (VERIFYING)
6. Buyer confirms delivery               (SETTLED, escrow released)
```

If the buyer disputes at step 6, the transaction enters DISPUTED state. Resolution can lead to SETTLED (seller paid) or REFUNDED (buyer returned).

## Database

SQLite with WAL mode and foreign key enforcement. Key tables:

- **accounts** -- agent balances
- **ledger_entries** -- double-entry bookkeeping log
- **escrows** -- locked funds with state machine
- **transactions** -- 8-state transaction lifecycle
- **transaction_history** -- append-only audit trail
- **skill_registry** -- capability search index
