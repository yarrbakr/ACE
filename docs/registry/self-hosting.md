# Self-Hosting the Registry

## Quick Start

```bash
pip install agent-capability-exchange
ace registry start
```

That's it. The registry is now running on `http://0.0.0.0:9000`.

## Configuration

```bash
ace registry start \
  --port 9000 \
  --host 0.0.0.0 \
  --db ./registry_data/registry.db \
  --prune-interval 60 \
  --prune-max-age 300
```

| Option | Default | Description |
|--------|---------|-------------|
| `--port` | `9000` | Port to listen on |
| `--host` | `0.0.0.0` | Bind address |
| `--db` | `./registry_data/registry.db` | SQLite database path |
| `--prune-interval` | `60` | How often to check for stale agents (seconds) |
| `--prune-max-age` | `300` | How long before an agent is considered stale (seconds) |

## Standalone Mode

The registry can also run without the `ace` CLI:

```bash
python -m registry
```

This uses environment variables for configuration:

| Variable | Default | Description |
|----------|---------|-------------|
| `ACE_REGISTRY_DB` | `registry_data/registry.db` | Database path |
| `PORT` | `9000` | Server port |

## Connecting Agents

Once your registry is running, agents connect like this:

```bash
# Initialize with registry discovery
ace init --name my-agent --discovery registry --registry-url http://your-host:9000

# Start and auto-register
ace start --public
```

## Verifying It Works

```bash
# Check registry health
curl http://localhost:9000/health

# List registered agents
curl http://localhost:9000/agents

# Search for capabilities
curl "http://localhost:9000/search?q=code+review"
```

## Behind a Reverse Proxy

If running behind nginx or similar:

```nginx
server {
    listen 443 ssl;
    server_name registry.example.com;

    location / {
        proxy_pass http://127.0.0.1:9000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

Agents then connect with:

```bash
ace init --discovery registry --registry-url https://registry.example.com
```
