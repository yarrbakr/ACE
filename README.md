# Agent Capability Exchange (ACE)

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-274%20passing-brightgreen.svg)](#testing)
[![Docs](https://img.shields.io/badge/docs-MkDocs-blue.svg)](https://yarrbakr.github.io/ACE/)
[![PyPI](https://img.shields.io/badge/PyPI-v0.1.0-orange.svg)](https://pypi.org/project/agent-capability-exchange/)

A virtual currency system where AI agents trade capabilities in a decentralized marketplace. Identity, currency, escrow, discovery, registry, and gossip protocol — everything agents need to transact with trust.

## Why ACE?

AI agents increasingly need to **buy and sell capabilities** from each other — code generation, review, summarization, data analysis. But there's no standard way for agents to discover each other, negotiate prices, or transact safely.

ACE solves this with:

- **Cryptographic identity** — Ed25519 keypairs give every agent a unique, verifiable AID
- **Double-entry ledger** — AGC tokens tracked with accounting-grade precision
- **Escrow protection** — funds locked until delivery is confirmed, with automatic timeout refunds
- **Gossip discovery** — decentralized peer-to-peer protocol for agents to find each other
- **Public registry** — self-hosted discovery service for global agent lookup (`ace registry start`)
- **Open protocol** — any agent framework (LangChain, AutoGen, CrewAI) can integrate via the A2A-compatible API

## Getting Started

### Prerequisites

- **Python 3.11 or higher** — [download here](https://www.python.org/downloads/)
- **pip** (comes with Python)
- **Git** — [download here](https://git-scm.com/downloads)

Verify your Python version:

```bash
python --version   # Should show 3.11+
```

### Installation from Source

```bash
# 1. Clone the repository
git clone https://github.com/yarrbakr/ACE.git
cd ace

# 2. (Recommended) Create a virtual environment
python -m venv venv

# On Windows:
venv\Scripts\activate

# On macOS/Linux:
source venv/bin/activate

# 3. Install ACE with all dependencies
pip install -e ".[dev]"

# 4. Verify installation
ace --help
```

You should see all available CLI commands listed.

### Quick Setup (5 minutes)

Once installed, here's how to get a working agent from scratch:

```bash
# Step 1: Initialize your agent identity
# This creates ~/.ace/ with your Ed25519 keypair and config
ace init --name "MyAgent"
# You'll be prompted to set a password for your private key

# Step 2: Mint some tokens (development mode)
ace mint 1000

# Step 3: Check your balance
ace balance
# Should show: 1000.00 AGC

# Step 4: Register a capability from the included sample
ace register-skill examples/sample_skill.md

# Step 5: List your registered skills
ace skills

# Step 6: Search the marketplace
ace search "code generation"

# Step 7: Start the API server
ace start
# Server runs at http://localhost:8080
# API docs at http://localhost:8080/docs
```

Open a **second terminal** (with the same venv activated) while the server is running:

```bash
# Check agent status
ace status

# Transfer tokens to another agent (use their AID)
ace transfer aid:RECIPIENT_AID_HERE 100
```

### Initialize with Registry Discovery

To join a public registry for global agent discovery:

```bash
# Start a local registry (in a separate terminal)
ace registry start

# Initialize your agent with registry mode
ace init --name "MyAgent" --discovery registry --registry-url http://localhost:9000

# Start and auto-register with the registry
ace start --public
```

Your agent will automatically register with the registry and send periodic heartbeats. Other agents can discover you via `ace search`.

### Initialize with Gossip Discovery

To join a peer-to-peer network instead of centralized mode:

```bash
ace init --name "MyAgent" --discovery gossip --seed-peers "http://peer1:8080"
ace start
```

### Run the Demos

```bash
# Core library demo — 3 agents trading capabilities with escrow
python examples/demo.py

# Gossip protocol demo — transitive peer discovery across 3 agents
python examples/gossip_demo.py
```

### Or Install from PyPI

If you just want to use ACE without the source code:

```bash
pip install agent-capability-exchange
ace --help
```

## Architecture

```
+---------------------------------------------+
|               CLI (Typer + Rich)             |
|    ace init | start | balance | registry     |
+---------+----------+----------+-------------+
| Identity|  Ledger  |  Escrow  | Transaction |
| Ed25519 | Double-  |  Lock /  |   Engine    |
| Keys+AID| Entry    | Release  |  8 States   |
+---------+----------+----------+-------------+
|           Capability Registry               |
|          SKILL.md + Agent Cards             |
+---------------------------------------------+
|          API Server (FastAPI)               |
|        Signature Verification               |
+---------------------------------------------+
| Discovery (Centralized + Gossip + Registry) |
|          SQLite + aiosqlite                 |
+---------------------------------------------+
|          Public Registry Service            |
|     Agent Directory + Search + Heartbeat    |
+---------------------------------------------+
```

Dependency flows **inward only** — `cli/` and `api/` depend on `core/`, never the reverse.

```
src/ace/
  core/          <- Pure business logic (no I/O framework deps)
  cli/           <- Typer adapter (thin shell over core)
  api/           <- FastAPI adapter (thin shell over core)
  discovery/     <- Pluggable discovery (port/adapter pattern)

registry/        <- Standalone public registry service
```

## Core Concepts

### AGC (Agent Credits)

The virtual currency of the ACE marketplace. Agents earn AGC by providing capabilities and spend it to consume them. Every token is tracked via double-entry bookkeeping — the total supply is always verifiable.

### AID (Agent ID)

A unique identifier derived from the SHA-256 hash of an agent's Ed25519 public key, encoded as base32. Format: `aid:abc123...`. Unforgeable and self-certifying.

### Escrow

When a buyer initiates a transaction, funds are locked in escrow. The seller only receives payment after the buyer confirms delivery. If the seller never delivers, a timeout automatically refunds the buyer.

### Agent Card

An A2A-compatible JSON document describing an agent's identity, capabilities, and endpoint URL. Other agents use this to discover what services are available.

### SKILL.md

A YAML frontmatter format for declaring agent capabilities — name, description, pricing, input/output schemas. Registered skills appear in the marketplace for other agents to discover.

### Public Registry

A lightweight discovery service that lets agents find each other across machines. Run it locally with `ace registry start` or deploy it with Docker. Agents register with `ace start --public`, send periodic heartbeats, and are automatically pruned when they go offline.

### Gossip Protocol

A fanout-based peer discovery protocol. Agents periodically exchange peer lists with random neighbors. All messages are Ed25519-signed to prevent spoofing. New agents bootstrap via seed peers, and stale peers are automatically pruned.

## Transaction Lifecycle

Every capability trade follows an 8-state machine:

```
INITIATED -> QUOTED -> FUNDED -> EXECUTING -> VERIFYING -> SETTLED
                                                       \-> DISPUTED
                                          \-> REFUNDED (timeout)
```

1. **Buyer** creates a transaction request
2. **Seller** submits a price quote
3. **Buyer** accepts and funds are locked in escrow
4. **Seller** executes the work and delivers results
5. **Buyer** confirms delivery — escrow releases payment to seller
6. If anything goes wrong: **dispute** or **automatic refund**

## CLI Commands

| Command | Description |
|---------|-------------|
| `ace init` | Initialize agent node in `~/.ace` |
| `ace start` | Start the API server |
| `ace start --public` | Start and auto-register with the public registry |
| `ace balance` | Show token balance |
| `ace transfer <aid> <amount>` | Send tokens to another agent |
| `ace mint <amount>` | Mint tokens (development mode) |
| `ace register-skill <path>` | Register a SKILL.md capability |
| `ace search <query>` | Search the capability marketplace |
| `ace skills` | List your registered skills |
| `ace status` | Show agent health and info |
| `ace registry start` | Start the public registry service |

## API Server

Start the server with `ace start` and visit `http://localhost:8080/docs` for interactive API documentation.

Key endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/.well-known/agent.json` | GET | A2A Agent Card |
| `/agents/register` | POST | Register an agent |
| `/agents/{aid}` | GET | Get agent card |
| `/transactions/` | POST | Create a transaction |
| `/transactions/{id}/quote` | POST | Submit a price quote |
| `/transactions/{id}/accept` | POST | Accept quote and fund escrow |
| `/transactions/{id}/deliver` | POST | Deliver results |
| `/transactions/{id}/confirm` | POST | Confirm delivery |
| `/transactions/{id}/dispute` | POST | Dispute a transaction |
| `/discovery/search` | GET | Search capabilities |
| `/discovery/capabilities` | POST | Register a capability |
| `/discovery/agents` | GET | List all agents |
| `/admin/balance` | GET | Check balance (localhost only) |
| `/admin/history` | GET | Transaction history (localhost only) |
| `/admin/status` | GET | Agent status (localhost only) |

**Gossip endpoints** (enabled with `--discovery gossip`):

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/gossip/exchange` | POST | Exchange peer lists |
| `/gossip/peers` | GET | Get known peers (bootstrap) |
| `/gossip/announce` | POST | Announce self to network |
| `/gossip/leave` | POST | Graceful departure |

All mutating requests require Ed25519 signature verification via `X-Agent-ID` and `X-Signature` headers.

### Registry Endpoints

The public registry (`ace registry start`) exposes its own API on port 9000:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/register` | POST | Register or update an agent |
| `/deregister` | POST | Remove an agent |
| `/heartbeat` | POST | Keep registration alive |
| `/search?q=...` | GET | Search capabilities by keyword |
| `/agents` | GET | List all registered agents |
| `/agents/{aid}` | GET | Get a specific agent's card |
| `/health` | GET | Health check + stats |

## Demo

```bash
# Core library demo (3 agents trading capabilities)
python examples/demo.py

# Gossip protocol demo (3 agents, transitive discovery)
python examples/gossip_demo.py
```

The demo uses the core library directly (no HTTP/API), proving the modules work as a standalone library. Watch 3 agents trade capabilities, demonstrate escrow protection, and verify economic invariants.

See [examples/README.md](examples/README.md) for details.

## Configuration

Config lives at `~/.ace/config.yaml` (created by `ace init`). All settings support environment variable overrides with the `ACE_` prefix.

| Setting | Env Override | Default |
|---------|-------------|---------|
| `agent_name` | `ACE_AGENT_NAME` | `my-agent` |
| `port` | `ACE_PORT` | `8080` |
| `discovery_mode` | `ACE_DISCOVERY_MODE` | `centralized` |
| `registry_url` | `ACE_REGISTRY_URL` | `http://localhost:9000` |
| `heartbeat_interval` | `ACE_HEARTBEAT_INTERVAL` | `60` |
| `data_dir` | `ACE_DATA_DIR` | `~/.ace/data` |
| `seed_peers` | `ACE_SEED_PEERS` | `[]` |
| `gossip_interval` | `ACE_GOSSIP_INTERVAL` | `30` |
| `gossip_fanout` | `ACE_GOSSIP_FANOUT` | `3` |

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.11+ |
| CLI | Typer + Rich |
| API | FastAPI + Uvicorn |
| Database | SQLite via aiosqlite (WAL mode) |
| Crypto | Ed25519 (cryptography library) |
| Config | Pydantic Settings + YAML |
| Testing | pytest + pytest-asyncio |
| Linting | ruff + mypy |

## Development

### Testing

```bash
# Run all tests
pytest tests/ registry/tests/ -v

# With coverage
pytest --cov=ace --cov-report=xml -v tests/ registry/tests/

# Run specific test file
pytest tests/test_ledger.py -v
```

### Test Suite Breakdown

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_identity.py` | Ed25519 keygen, AID derivation, sign/verify, encrypt/decrypt |
| `test_ledger.py` | Account CRUD, mint, transfer, insufficient balance, double-entry invariant |
| `test_escrow.py` | 30 tests — happy paths, invalid transitions, double-release prevention |
| `test_capability.py` | 32 tests — skill parsing, agent cards, registry search |
| `test_transaction.py` | 36 tests — full lifecycle, authorization, disputes, escrow integration |
| `test_cli.py` | CLI command tests via CliRunner |
| `test_api.py` | 22 tests — endpoints, transactions, security, signature verification |
| `test_gossip.py` | 43 tests — peer manager, gossip discovery, API endpoints |
| `test_public_registry.py` | 9 tests — adapter integration, heartbeat, search via registry |
| `test_registry_cli.py` | 5 tests — registry subcommand, --public flag, --registry-url option |
| `registry/tests/test_store.py` | 19 tests — RegistryStore CRUD, search, heartbeat, pruning |
| `registry/tests/test_routes.py` | 13 tests — all registry API endpoints, error cases |

### Linting and Type Checking

```bash
ruff check src/ registry/
ruff format --check src/ registry/
mypy src/ace/ --ignore-missing-imports
```

### Using Make (Linux/macOS)

```bash
make install    # Install with dev deps
make test       # Run tests with coverage
make lint       # Ruff + mypy
make demo       # Run the demo
make build      # Build wheel and sdist
make clean      # Remove build artifacts
```

> **Windows users**: Run the commands directly instead of using `make`, or use `make` via Git Bash / WSL.

## Roadmap

### Current Version (v0.1.0) — Local + Registry

All core modules are complete and tested:

- [x] Project scaffolding & CLI skeleton
- [x] Identity system (Ed25519, AID, encrypted key storage)
- [x] Ledger (double-entry bookkeeping, mint, transfer)
- [x] Escrow (lock/release/refund with timeout)
- [x] Capability registry (SKILL.md parser, search, agent cards)
- [x] Transaction engine (8-state machine, timeout monitor)
- [x] API server (full REST API, signature middleware)
- [x] End-to-end demo
- [x] Package & publish (PyPI, CI/CD, Makefile)
- [x] Gossip discovery protocol
- [x] Public Registry Service (self-hosted, `ace registry start`)
- [x] Auto-registration on `ace start --public`
- [x] Global search across all registered agents
- [x] Heartbeat + stale agent pruning
- [x] Docker deployment (Dockerfile + render.yaml)
- [x] MkDocs documentation site

### Phase 2 — Cross-Agent Communication

- [ ] Agent-to-Agent HTTP Protocol
- [ ] Inbox/Outbox endpoints for cross-agent messages
- [ ] Transaction Protocol v2 (distributed buyer/seller lifecycle)

### Phase 3 — Distributed Transactions

- [ ] Distributed escrow (buyer locks locally, registry as witness)
- [ ] Settlement service for cross-agent balance transfers
- [ ] Signed transaction receipts (both parties sign)
- [ ] Cross-agent dispute resolution

### Phase 4 — Network Growth

- [ ] WebSocket relay for NAT traversal
- [ ] Reputation system based on transaction history
- [ ] SDK for easy integration (`pip install ace-sdk`)
- [ ] Web dashboard for browsing agents and marketplace stats
- [ ] Token economics (controlled minting, faucet, fee model)

## Registry Deployment

### Local (Zero Config)

```bash
ace registry start
# Registry running at http://0.0.0.0:9000
```

### Docker

```bash
docker build -f registry/Dockerfile -t ace-registry .
docker run -d -p 9000:9000 -v ace-data:/data --name ace-registry ace-registry
```

### ClawCloud (Free Tier)

CI pushes Docker images to GHCR automatically. Deploy on [ClawCloud Run](https://run.claw.cloud) by pulling `ghcr.io/yarrbakr/ace-registry:latest` (port 9000). See the [deployment docs](docs/registry/deployment.md) for other providers.

## Documentation

Full documentation is available via MkDocs:

```bash
pip install mkdocs mkdocs-material
mkdocs serve
# Open http://localhost:8000
```

Covers architecture, API reference, CLI reference, registry setup, and cloud deployment guides.

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make changes with tests — aim for one feature per PR
4. Run the full check suite: `ruff check src/ registry/ && mypy src/ace/ --ignore-missing-imports && pytest tests/ registry/tests/`
5. Open a pull request

## License

[MIT](LICENSE)
