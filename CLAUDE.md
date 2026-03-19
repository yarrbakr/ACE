# ACE — Agent Capability Exchange

A pip-installable CLI tool and API server where AI agents trade capabilities using a virtual currency (AGC tokens) in a decentralized marketplace.

## Tech Stack

- **Language**: Python 3.11+ (strict mypy, ruff linting)
- **CLI**: Typer with Rich markup (`ace` command)
- **API**: FastAPI + Uvicorn
- **Database**: SQLite via aiosqlite (WAL mode, FK enforcement)
- **Crypto**: `cryptography` library (Ed25519 keys, Fernet encryption, PBKDF2)
- **Config**: Pydantic Settings backed by `~/.ace/config.yaml`
- **Build**: setuptools with src/ layout
- **Testing**: pytest + pytest-asyncio (asyncio_mode = "auto")

## Architecture

Dependency flows **inward only** — `cli/` and `api/` depend on `core/`, never the reverse.

```
src/ace/
  core/          <- Pure business logic (NO I/O framework deps)
  cli/           <- Typer adapter (thin shell over core)
  api/           <- FastAPI adapter (thin shell over core)
  discovery/     <- Pluggable discovery (port/adapter pattern)

registry/        <- Standalone public registry service (FastAPI + SQLite)
```

## Directory Map

```
src/ace/
  __init__.py              # Package root, exports __version__ = "0.1.0"
  core/
    __init__.py            # Exports: config, exceptions, identity, ledger, escrow, capability, transaction
    config.py              # AceSettings (Pydantic), load_settings(), ensure_ace_dir(), write_default_config()
    exceptions.py          # ACEError hierarchy: InsufficientBalanceError, AccountNotFoundError, InvalidEscrowStateError, InvalidTransitionError, UnauthorizedActionError, ConfigNotFoundError, SkillParseError, DecryptionError
    identity.py            # AgentIdentity class: Ed25519 keygen, AID derivation (sha256->b32), sign/verify, encrypted save/load (Fernet+PBKDF2)
    ledger.py              # Ledger class: double-entry bookkeeping, transfer(), mint(), get_balance(), get_transaction_history(). Uses aiosqlite. System accounts: SYSTEM:ISSUANCE, SYSTEM:ESCROW, SYSTEM:BURN, SYSTEM:FEES. transfer() accepts optional entry_type param.
    escrow.py              # EscrowManager class + Escrow dataclass. create_escrow(), release_escrow(), refund_escrow(), get_escrow(), check_expired_escrows(). DI: takes Ledger in constructor. Atomic state transitions via UPDATE...WHERE state='LOCKED'.
    capability.py          # SkillPricing, SkillDefinition (Pydantic v2), SkillParser (YAML frontmatter via safe_load), generate_agent_card() (A2A protocol), CapabilityRegistry (SQLite + in-memory cache: register, unregister, search, get_agent_card, list_skills)
    transaction.py         # TransactionState(str, Enum) 8 states, Transaction(Pydantic), VALID_TRANSITIONS dict, TransactionEngine (DI: Ledger+EscrowManager, _transition choke point, authorization checks), TimeoutMonitor (asyncio background task)
    schema.sql             # SQLite schema: accounts, ledger_entries, agents, escrows, capabilities, transactions (8-state), transaction_history (audit trail)
  cli/
    main.py                # Typer app. Entry point: ace = "ace.cli.main:app". Commands: init, start, balance, transfer, mint, register-skill, search, skills, status, registry. Registry is a Typer subgroup via add_typer()
    commands/
      init.py              # ace init: creates ~/.ace/, generates Ed25519 identity, saves encrypted key + config.yaml. --discovery gossip/registry --seed-peers --registry-url flags
      start.py             # ace start: loads config+identity, launches uvicorn programmatically. --port, --host, --public flags. --public overrides discovery_mode to REGISTRY. Windows 0.0.0.0 firewall warning
      registry.py          # ace registry start: launches registry server via uvicorn. --port 9000, --host 0.0.0.0, --db, --prune-interval, --prune-max-age
      wallet.py            # ace balance, ace transfer, ace mint — IMPLEMENTED. Uses Ledger + Identity
      skills.py            # ace register-skill (parse + validate + copy to ~/.ace/skills/), ace search (Rich table), ace skills (list registered)
      status.py            # ace status: calls GET /admin/status via httpx, handles connection refused gracefully
  api/
    server.py              # create_app() FastAPI factory. Lifespan initializes Ledger, EscrowManager, TransactionEngine, CapabilityRegistry, TimeoutMonitor, GossipDiscovery (when discovery_mode=gossip), and PublicRegistryDiscovery (when discovery_mode=registry). CORS + signature middleware. Routes: /agents, /transactions, /discovery, /admin, /gossip (gossip mode only). Health at /health. Agent Card at /.well-known/agent.json
    middleware.py           # SignatureVerificationMiddleware (BaseHTTPMiddleware): Ed25519 sig verification on POST/PUT/DELETE. GET/HEAD/OPTIONS pass through. Resolves public key via local identity or agents table
    models.py              # Pydantic v2 request/response models: ErrorResponse, CreateTransactionRequest, SubmitQuoteRequest, DeliverResultRequest, DisputeRequest, TransactionResponse, TransactionListResponse, RegisterCapabilityRequest, CapabilitySearchResponse, BalanceResponse, HistoryResponse, StatusResponse, AgentCardResponse
    deps.py                # DI via Depends(): get_settings(), get_ledger(), get_escrow_manager(), get_transaction_engine(), get_capability_registry(), get_identity(). All pull from request.app.state
    routes/
      agent.py             # POST /agents/register (upserts agents table + registry), GET /agents/{aid} (lookup agent card)
      transactions.py      # Full 8-state lifecycle: POST / (create), POST /{tx_id}/quote, /accept, /deliver, /confirm, /dispute. GET /{tx_id}, GET / (list with role/state filters)
      discovery.py         # GET /search (keyword + max_price filter), POST /capabilities (register skill), GET /agents (list all)
      admin.py             # GET /balance, /history, /status — localhost-only (127.0.0.1, ::1, testclient guard). Status includes discovery_mode, known_peers, seed_peers
      gossip.py            # POST /gossip/exchange (signed peer list exchange), GET /gossip/peers (bootstrap), POST /gossip/announce (self-announce), POST /gossip/leave (graceful departure). Only mounted when discovery_mode=gossip. Rate-limited, signature-verified
  discovery/
    base.py                # DiscoveryAdapter ABC: register(), deregister(), search(), get_agent(), list_agents()
    centralized.py         # CentralizedDiscovery(DiscoveryAdapter) — delegates to CapabilityRegistry, lazy-initialized
    gossip_models.py       # PeerInfo, GossipMessage, GossipConfig, AnnounceRequest, LeaveRequest (Pydantic v2 wire format)
    peer_manager.py        # PeerManager: pure in-memory peer state (add, remove, merge, prune, search). No I/O, no async
    gossip.py              # GossipDiscovery(DiscoveryAdapter): full gossip protocol engine. httpx.AsyncClient for peer communication, background gossip loop, Ed25519 signed messages, seed peer bootstrap
    public_registry.py     # PublicRegistryDiscovery(DiscoveryAdapter): HTTP client adapter for public registry. httpx.AsyncClient, background heartbeat loop via asyncio.create_task(), register/deregister/search/list via registry REST API

registry/
  __init__.py              # Package root, __version__ = "0.1.0"
  schema.sql               # SQLite schema: registered_agents (with heartbeat_at), registry_capabilities (CASCADE delete). WAL mode, FK enforcement, indexes on name/price/heartbeat
  models.py                # Pydantic v2 models: RegisterAgentRequest, HeartbeatRequest, DeregisterRequest, SearchResponse, AgentListResponse, RegistryStatsResponse
  store.py                 # RegistryStore class: aiosqlite + in-memory cache. Pattern follows CapabilityRegistry. Methods: initialize(), register_agent() (upsert via ON CONFLICT), deregister_agent(), heartbeat(), get_agent(), search() (OR-matching with JOIN), list_agents(), prune_stale(), agent_count()
  routes.py                # FastAPI router: POST /register (201), POST /deregister, POST /heartbeat, GET /search, GET /agents, GET /agents/{aid}, GET /health. Error envelope matches ace API pattern. Endpoints returning dict|JSONResponse use response_model=None
  app.py                   # create_registry_app() factory + PruneTask background task. PruneTask follows TimeoutMonitor pattern. Lifespan initializes store, starts pruner, records start_time
  __main__.py              # Standalone runner: python -m registry. Reads ACE_REGISTRY_DB + PORT env vars
  Dockerfile               # Multi-stage Python 3.13-slim build, exposes 9000, healthcheck
  .dockerignore
  tests/
    __init__.py
    conftest.py            # Fixtures: registry_db(tmp_path), registry_client (TestClient as context manager for lifespan), SAMPLE_AGENT_CARD, SAMPLE_AGENT_CARD_2
    test_store.py          # 19 tests: CRUD, search, heartbeat, prune, upsert, agent_count
    test_routes.py         # 13 tests: all endpoints, 404s, search filters, health stats
```

## What's Implemented vs Stubbed

| Module | Status | Step |
|--------|--------|------|
| Project scaffolding & CLI skeleton | DONE | Step 1 |
| Identity (Ed25519, AID, ace init) | DONE | Step 2 |
| Ledger (double-entry, mint, transfer, ace balance/transfer/mint) | DONE | Step 3 |
| Escrow (lock/release/refund) | DONE | Step 4 |
| Capability (SKILL.md parser, registry, ace register-skill/search/skills) | DONE | Step 5 |
| Transaction engine (8-state machine, timeout monitor) | DONE | Step 6 |
| API server (ace start, full REST API, signature middleware) | DONE | Step 7 |
| End-to-end demo (`examples/demo.py`) | DONE | Step 8 |
| Package & Publish (README, CI, Makefile, build) | DONE | Step 9 |
| Discovery (gossip protocol) | DONE | Step 10 |
| Public Registry Service (`registry/`, `ace registry start`) | DONE | Phase 1 |
| Registry Discovery Adapter (`PublicRegistryDiscovery`) | DONE | Phase 1 |
| Auto-registration (`ace start --public`, heartbeat loop) | DONE | Phase 1 |
| Docker deployment (Dockerfile + render.yaml) | DONE | Phase 1 |
| MkDocs documentation site | DONE | Phase 1 |

## Key Patterns & Conventions

- **All async**: DB operations use `async/await` with aiosqlite
- **CLI wraps async**: CLI commands use `asyncio.run()` to call async core methods
- **Double-entry bookkeeping**: Every transfer creates exactly 2 ledger entries (DEBIT + CREDIT). Sum of all DEBITs == sum of all CREDITs
- **System accounts go negative**: SYSTEM:ISSUANCE balance goes negative to track total money supply
- **AID format**: `aid:{base32_lowercase_no_padding}` derived from SHA-256 of Ed25519 public key (first 16 bytes)
- **Encrypted identity**: Private key stored as `salt(16 bytes) + Fernet(PBKDF2(password, salt), raw_key)` at `~/.ace/identity.key`
- **Config location**: `~/.ace/config.yaml` (created by `ace init`)
- **DB location**: `~/.ace/data/ace.db`
- **Env overrides**: All settings support `ACE_` prefix env vars (e.g., `ACE_PORT=9090`)
- **Port/adapter pattern**: Discovery is pluggable via `DiscoveryAdapter` ABC
- **Entry types**: ISSUANCE, TRANSFER, FEE, BURN, ESCROW_LOCK, ESCROW_RELEASE, ESCROW_REFUND
- **Escrow states**: LOCKED -> RELEASED (seller paid) | REFUNDED (buyer returned). Terminal states are immutable.
- **Escrow atomicity**: State transitions use `UPDATE ... WHERE state = 'LOCKED'` + rowcount check to prevent double-release/refund
- **Escrow DI**: EscrowManager takes Ledger as constructor arg, uses `ledger._db_path` for its own connections
- **Transaction states**: INITIATED -> QUOTED -> FUNDED -> EXECUTING -> VERIFYING -> SETTLED | DISPUTED | REFUNDED
- **Transaction DI**: TransactionEngine takes Ledger + EscrowManager as constructor args
- **VALID_TRANSITIONS**: Data-driven dict mapping each state to its legal next states. SETTLED and REFUNDED are terminal (empty sets)
- **_transition() choke point**: All state changes flow through _transition() — validates legality, actor authorization, logs to transaction_history
- **Authorization map**: submit_quote=seller, accept_quote=buyer, deliver_result=seller, confirm_delivery=buyer, dispute=buyer
- **TimeoutMonitor**: asyncio background task checks every N seconds for expired transactions, auto-refunds FUNDED/EXECUTING, auto-disputes VERIFYING
- **Transaction history**: Append-only audit trail in transaction_history table (from_state, to_state, actor_aid, timestamp, note)
- **SKILL.md format**: YAML frontmatter between `---` markers, parsed via `yaml.safe_load`. Supports both `price: N` shorthand and full `pricing:` block
- **CapabilityRegistry**: SQLite `skill_registry` table with in-memory cache. Search uses LIKE with OR-matching across words. Parameterized queries only
- **Agent Card**: A2A-compatible JSON with `name`, `url`, `capabilities[]`, `authentication` (ed25519), `aid`
- **Skills directory**: `~/.ace/skills/` stores copies of registered SKILL.md files
- **App factory**: `create_app(settings, identity)` returns configured FastAPI instance. No global app variable
- **Lifespan pattern**: `asynccontextmanager` lifespan (not deprecated `@app.on_event`). Initializes DB, core modules, timeout monitor on startup; cleans up on shutdown
- **Signature middleware**: `SignatureVerificationMiddleware` (BaseHTTPMiddleware) — verifies Ed25519 signatures on POST/PUT/DELETE via `X-Agent-ID` + `X-Signature` headers. GET/HEAD/OPTIONS pass through unsigned. Public key resolved from local identity first, then agents table
- **Error envelope**: All API errors use `{"status": "error", "error": {"code": "...", "message": "..."}}` format
- **Admin localhost guard**: Admin endpoints check `request.client.host` against `127.0.0.1`, `::1`, `localhost`, `testclient`
- **Server default host**: `127.0.0.1` (not `0.0.0.0`) for security. Windows firewall warning on `0.0.0.0`
- **Uvicorn launch**: Programmatic `uvicorn.run(app, host, port)` — not subprocess
- **TestClient signing**: Tests use `content=body_bytes` (not `json=`) with compact JSON (`separators=(",",":")`) to match middleware body reads
- **Demo**: `examples/demo.py` uses core library directly (no CLI/API/HTTP). Rich output with plain text fallback. Temp DB via `tempfile.mkdtemp()`. All ASCII output (no Unicode box-drawing) for Windows cp1252 compatibility. 3 scenarios with balance assertions + total supply invariant check
- **Gossip protocol**: Fanout-based periodic peer exchange. Every N seconds, pick random peers, exchange peer lists, merge, prune stale. Result: all agents eventually know about all other agents
- **PeerInfo versioning**: Monotonic `version` counter prevents stale overwrites — only accept peer data with version > existing
- **Signed gossip**: Ed25519 signatures on all peer exchanges. Invalid/unsigned messages rejected before merge. Anti-spoofing: agents can only announce their own AID
- **Seed peers**: Bootstrap-only URLs for initial network join. Not required after first gossip round populates the peer list
- **PeerManager**: Pure in-memory dict[str, PeerInfo]. No I/O, no async — trivially testable. SRP: handles peer state only
- **GossipDiscovery DI**: Takes AgentIdentity + AceSettings in constructor. Creates PeerManager + httpx.AsyncClient internally
- **Gossip config**: `seed_peers`, `gossip_interval` (30s default), `gossip_fanout` (3 default) in AceSettings. ACE_ env prefix works
- **Gossip endpoints conditional**: `/gossip/*` routes only mounted when `discovery_mode == "gossip"`. Centralized mode is unchanged
- **Rate limiting**: Gossip exchange endpoint limits to 10 requests per peer per minute to prevent flooding
- **Gossip demo**: `examples/gossip_demo.py` — 3 agents, transitive discovery (A->B->C), search across gossip network, peer pruning
- **Registry service**: Standalone FastAPI app in `registry/` subfolder. Separate from agent API. Own schema.sql, own SQLite DB at `./registry_data/registry.db`
- **RegistryStore**: SQLite + in-memory cache (follows CapabilityRegistry pattern). Connection-per-operation. Upsert via `INSERT ... ON CONFLICT(aid) DO UPDATE`
- **PruneTask**: Background asyncio task that periodically removes stale agents (follows TimeoutMonitor pattern from transaction.py). Configurable interval + max_age
- **Registry app factory**: `create_registry_app(db_path, prune_interval, prune_max_age)` — same pattern as `create_app()`. Lifespan initializes store + pruner
- **Registry response_model=None**: Endpoints returning `dict | JSONResponse` must have `response_model=None` to avoid FastAPI Pydantic serialization errors
- **PublicRegistryDiscovery DI**: Takes `registry_url` + `heartbeat_interval` in constructor. Creates httpx.AsyncClient internally
- **Heartbeat loop**: `PublicRegistryDiscovery.register()` starts `asyncio.create_task(_heartbeat_loop())`. `deregister()`/`stop()` cancels it + closes httpx client
- **--public flag**: `ace start --public` overrides `settings.discovery_mode` to `DiscoveryMode.REGISTRY` at runtime. Graceful failure if registry not reachable
- **Registry CLI**: `ace registry start` is a Typer subgroup (`app.add_typer(registry_app)`). Follows `ace start` pattern (Rich banner, uvicorn.run)
- **Registry conditional lifespan**: In `server.py`, `elif settings.discovery_mode == DiscoveryMode.REGISTRY` branch creates PublicRegistryDiscovery, builds agent card, tries register (try/except for graceful failure)
- **MockTransport testing**: Adapter tests use `httpx.MockTransport` to forward from async httpx client to sync TestClient. Requires TestClient as context manager for lifespan
- **Render deployment**: `render.yaml` in repo root for one-click Render deploy (Docker, free tier, /health check, 1GB disk)
- **MkDocs docs**: `mkdocs.yml` with Material theme, nav structure. Docs in `docs/` folder. `mkdocs serve` for local preview, `mkdocs build --strict` in CI

## Test Structure

```
tests/
  conftest.py              # Shared fixtures: cli_runner, tmp_ace_dir, identity, password, encrypted_key_path, tmp_db_path, ledger, two_funded_accounts, escrow_manager, escrow_setup, transaction_engine, tx_setup
  test_identity.py         # Ed25519 keygen, AID derivation, sign/verify, encrypt/decrypt round-trip
  test_ledger.py           # Account CRUD, mint, transfer, insufficient balance, race conditions, double-entry invariant
  test_escrow.py           # 30 tests: happy paths, invalid transitions, double-release/refund prevention, timeout detection, ledger integration
  test_capability.py       # 32 tests: SkillPricing validation, SkillParser (valid/invalid/edge cases/sample_skill.md), AgentCard generation, CapabilityRegistry (register/unregister/search/max_price/list)
  test_transaction.py      # 36 tests: full lifecycle, invalid transitions, authorization (6 wrong-actor), disputes, escrow integration, history audit, edge cases, listing, refund paths
  test_cli.py              # CLI command tests via CliRunner
  test_api.py              # 22 tests: Agent Card (3), health (1), transactions lifecycle (7), discovery (2), admin (3), security (6). Uses FastAPI TestClient + Ed25519 signed requests
  test_gossip.py           # 43 tests: PeerManager unit tests (22: add/remove/merge/prune/search), GossipDiscovery integration (13: lifecycle/adapter/crypto/self-loop), API endpoint tests (6: exchange/peers/announce/leave/centralized-guard), Status with gossip (2)
  test_public_registry.py  # 9 tests: adapter integration via MockTransport+TestClient, register+search, register+list, deregister, heartbeat lifecycle, max_price filter, not found
  test_registry_cli.py     # 5 tests: registry subcommand in help, registry start --help options, --public flag in start help, --registry-url in init help, "registry" in discovery modes

registry/tests/
  conftest.py              # Fixtures: registry_db(tmp_path), registry_client (TestClient with lifespan context manager), SAMPLE_AGENT_CARD, SAMPLE_AGENT_CARD_2
  test_store.py            # 19 tests: RegistryStore CRUD, search (keyword, max_price, OR-matching), heartbeat, prune_stale, upsert, agent_count, empty results
  test_routes.py           # 13 tests: all 7 registry API endpoints, 404s, search filters, health stats, deregister, heartbeat, upsert behavior
```

**Test password**: `super-secret-test-pw-123` (in conftest.py)

## Commands

```bash
pip install -e ".[dev]"    # Install with dev deps
ace --help                 # Show all CLI commands
ace init --name my-agent   # Bootstrap ~/.ace/ with identity + config (centralized mode)
ace init --name my-agent --discovery gossip --seed-peers "http://peer1:8080"  # Gossip mode
ace init --name my-agent --discovery registry --registry-url http://localhost:9000  # Registry mode
ace balance                # Show token balance
ace transfer <aid> <amt>   # Send tokens
ace mint <amount>          # Mint tokens (dev only)
ace register-skill ./f.md  # Register a SKILL.md capability
ace search "query"         # Search capabilities (--max-price N)
ace skills                 # List registered skills
ace start                  # Launch API server (requires ace init first)
ace start --public         # Launch + auto-register with public registry
ace status                 # Show agent status (server must be running)
ace registry start         # Start public registry on port 9000
python -m registry         # Standalone registry (no ace CLI needed)
pytest tests/ registry/tests/  # Run all tests (~274 total)
ruff check src/ registry/  # Lint
mypy src/ace/              # Type check
mkdocs serve               # Preview docs at http://localhost:8000
python -m build            # Build wheel + sdist into dist/
```

## Makefile Targets

```bash
make install    # pip install -e ".[dev]"
make test       # pytest --cov=ace -v
make lint       # ruff check + ruff format --check + mypy
make demo       # python examples/demo.py
make build      # python -m build
make clean      # Remove build artifacts, __pycache__, caches
```

## CI/CD

GitHub Actions workflow at `.github/workflows/ci.yml`:
- **test** job: Python 3.11/3.12/3.13 × ubuntu-latest/windows-latest (6 combinations). Runs `pytest --cov=ace --cov-report=xml -v tests/ registry/tests/`. Uploads coverage to Codecov on Python 3.13 + ubuntu only
- **lint** job: ubuntu-latest, Python 3.13. Runs `ruff check src/ registry/`, `ruff format --check src/ registry/`, `mypy --ignore-missing-imports`
- **docs** job: ubuntu-latest, Python 3.13. Runs `mkdocs build --strict`. Deploys to GitHub Pages via `peaceiris/actions-gh-pages@v3` on push to main only
- Triggers on push to main and PRs to main

## Packaging

- **Build tool**: `python -m build` (setuptools backend)
- **Package name**: `agent-capability-exchange` (PyPI), importable as `ace`
- **Entry point**: `ace = "ace.cli.main:app"` (Typer app)
- **Package data**: `ace: core/schema.sql`, `registry: schema.sql` included via `[tool.setuptools.package-data]`
- **Package find**: `where = ["src", "."]`, `include = ["ace*", "registry*"]` — includes both ace and registry packages
- **Dev extras**: `pip install -e ".[dev]"` — pytest, pytest-asyncio, pytest-cov, ruff, mypy, build, mkdocs, mkdocs-material
- **Keywords**: ai, agents, currency, marketplace, capabilities, agent-to-agent, a2a, capability-exchange, agent-marketplace, escrow, ed25519
- **Classifiers**: Alpha, Python 3.11/3.12/3.13, OS Independent, Typed

## Development Roadmap (Steps in Documents/prompts.md)

All 10 local steps + Phase 1 (Public Registry) are complete. The full step-by-step build plan with copy-paste prompts is in `Documents/prompts.md`. Enhanced versions of each step are in `Documents/step{N}_prompt_enhanced.md`. Global network roadmap is in `Documents/global_network_plan.md`.

## Important Files for Each Step

- **Step 4 (Escrow)**: Edit `src/ace/core/escrow.py`, update `schema.sql`, write `tests/test_escrow.py`
- **Step 5 (Capability)**: Edit `src/ace/core/capability.py`, `src/ace/cli/commands/skills.py`, `src/ace/discovery/centralized.py`, write `tests/test_capability.py`
- **Step 6 (Transaction)**: Edit `src/ace/core/transaction.py`, `src/ace/api/routes/transactions.py`, write `tests/test_transaction.py`
- **Step 7 (API Server)**: Edit `src/ace/api/server.py`, `src/ace/api/deps.py`, all routes, `src/ace/cli/commands/start.py`, `src/ace/cli/commands/status.py`
- **Step 8 (Demo)**: `examples/demo.py` (self-contained, uses core library directly, 3 scenarios: simple tx, circulation, escrow timeout), `examples/README.md`
- **Step 9 (Package & Publish)**: `README.md` (full rewrite), `.github/workflows/ci.yml`, `Makefile`, `pyproject.toml` (classifiers, keywords, package-data for schema.sql), `.gitignore` (.env, *.db, coverage.xml)
- **Step 10 (Gossip Discovery)**: `src/ace/discovery/gossip_models.py` (new), `src/ace/discovery/peer_manager.py` (new), `src/ace/discovery/gossip.py` (replaced stub), `src/ace/api/routes/gossip.py` (new), `src/ace/api/server.py` (modified: conditional gossip adapter + routes), `src/ace/core/config.py` (modified: seed_peers, gossip_interval, gossip_fanout fields), `src/ace/cli/commands/init.py` (modified: --discovery, --seed-peers), `src/ace/cli/commands/status.py` (modified: gossip info), `src/ace/api/routes/admin.py` (modified: gossip fields in status), `src/ace/api/models.py` (modified: StatusResponse gossip fields), `tests/test_gossip.py` (new), `examples/gossip_demo.py` (new)
- **Phase 1 (Public Registry)**: `registry/__init__.py`, `registry/schema.sql`, `registry/models.py`, `registry/store.py`, `registry/routes.py`, `registry/app.py`, `registry/__main__.py`, `registry/Dockerfile`, `registry/.dockerignore` (all new). `registry/tests/conftest.py`, `registry/tests/test_store.py`, `registry/tests/test_routes.py` (new tests). `src/ace/discovery/public_registry.py` (new adapter). `src/ace/cli/commands/registry.py` (new CLI). `src/ace/core/config.py` (modified: DiscoveryMode.REGISTRY, heartbeat_interval). `src/ace/api/server.py` (modified: registry discovery lifespan). `src/ace/cli/main.py` (modified: registry subgroup). `src/ace/cli/commands/start.py` (modified: --public flag). `src/ace/cli/commands/init.py` (modified: --registry-url). `tests/test_public_registry.py`, `tests/test_registry_cli.py` (new tests). `render.yaml`, `mkdocs.yml`, `docs/` folder (new deployment + docs). `pyproject.toml`, `.github/workflows/ci.yml` (modified: packaging + CI)
