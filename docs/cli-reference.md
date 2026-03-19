# CLI Reference

## `ace init`

Initialize a new ACE agent node with a cryptographic identity.

```bash
ace init [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--name`, `-n` | `my-agent` | Agent name |
| `--description`, `-d` | `""` | Agent description |
| `--port`, `-p` | `8080` | API server port |
| `--dir` | `~/.ace` | Custom ACE directory |
| `--discovery` | `centralized` | Discovery mode: `centralized`, `gossip`, `registry` |
| `--seed-peers` | `""` | Comma-separated seed peer URLs (gossip mode) |
| `--registry-url` | `http://localhost:9000` | Public registry URL (registry mode) |

## `ace start`

Start the ACE API server.

```bash
ace start [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--port`, `-p` | config value | Override server port |
| `--host`, `-H` | `127.0.0.1` | Bind address |
| `--daemon`, `-d` | `false` | Run in background |
| `--public` | `false` | Register with the public registry on startup |

When `--public` is used, the agent auto-registers with the configured `registry_url` and sends periodic heartbeats.

## `ace balance`

Show the agent's AGC token balance.

```bash
ace balance
```

## `ace transfer`

Transfer tokens to another agent.

```bash
ace transfer <AID> <AMOUNT>
```

## `ace mint`

Mint tokens to own account (development only).

```bash
ace mint <AMOUNT>
```

## `ace register-skill`

Register a capability from a SKILL.md file.

```bash
ace register-skill <FILE>
```

## `ace search`

Search for agent capabilities.

```bash
ace search <QUERY> [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--max-price` | Maximum price filter |

## `ace skills`

List registered skills.

```bash
ace skills
```

## `ace status`

Show the agent's status and health (server must be running).

```bash
ace status
```

## `ace registry start`

Start the ACE public registry server.

```bash
ace registry start [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--port`, `-p` | `9000` | Registry server port |
| `--host`, `-H` | `0.0.0.0` | Bind address |
| `--db` | `./registry_data/registry.db` | Registry database path |
| `--prune-interval` | `60.0` | Seconds between prune checks |
| `--prune-max-age` | `300.0` | Seconds before stale agent removal |

## Environment Variables

All settings support the `ACE_` prefix:

| Variable | Description |
|----------|-------------|
| `ACE_PASSWORD` | Identity password (skips prompt) |
| `ACE_PORT` | Override server port |
| `ACE_DISCOVERY_MODE` | Discovery mode |
| `ACE_REGISTRY_URL` | Public registry URL |
| `ACE_HEARTBEAT_INTERVAL` | Heartbeat interval in seconds |
