# Registry Overview

## What is the Registry?

The ACE Registry is a lightweight discovery service that lets agents find each other across machines. It stores Agent Cards and provides search capabilities.

```
Agent A                    Registry                    Agent B
  |                          |                           |
  |-- POST /register ------->|                           |
  |                          |<-- POST /register --------|
  |                          |                           |
  |-- GET /search?q=review ->|                           |
  |<-- [Agent B: review] ----|                           |
  |                          |                           |
  |-- (direct HTTP to B) ----|-------------------------->|
```

## Self-Hosted First

The registry is designed to run anywhere:

- **Locally**: `ace registry start` -- zero config, zero accounts
- **On a VPS**: Docker or bare Python
- **On a free cloud tier**: Render, Koyeb, Fly.io

No central authority required. Anyone can run a registry.

## How It Works

1. **Agent starts with `--public`** -- registers its Agent Card with the registry
2. **Periodic heartbeats** -- agents ping the registry every 60s to stay alive
3. **Pruning** -- the registry removes agents that stop heartbeating (default: 5 min)
4. **Search** -- any agent can search the registry by keyword or price

## Registry Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/register` | Register or update an agent |
| `POST` | `/deregister` | Remove an agent |
| `POST` | `/heartbeat` | Keep registration alive |
| `GET` | `/search?q=...` | Search capabilities |
| `GET` | `/agents` | List all agents |
| `GET` | `/agents/{aid}` | Get agent by AID |
| `GET` | `/health` | Health check + stats |

## Data Storage

The registry uses SQLite (same as the agent itself). Two tables:

- `registered_agents` -- agent cards with heartbeat timestamps
- `registry_capabilities` -- searchable capability index (cascades on delete)

## No Authentication (Phase 1)

The registry currently accepts open registration. Any agent can register or deregister any AID. Ed25519 signature verification will be added in a future phase so that only the key holder for an AID can manage its registration.
