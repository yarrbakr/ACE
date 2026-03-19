# Cloud Deployment

Deploy the ACE registry to a free cloud provider for global access.

## Render (Recommended)

Render offers a free tier with no credit card required.

### Setup

1. Push your code to GitHub
2. Go to [render.com](https://render.com) and sign in with GitHub
3. Click **New > Web Service**
4. Connect your repository
5. Render will auto-detect the `render.yaml` and configure everything

### Manual Setup

If you prefer manual configuration:

| Setting | Value |
|---------|-------|
| Runtime | Docker |
| Dockerfile Path | `registry/Dockerfile` |
| Docker Context | `.` |
| Instance Type | Free |
| Health Check Path | `/health` |

!!! note "Free tier sleep"
    Render's free tier sleeps after 15 minutes of inactivity. Use a free uptime monitor (e.g., Better Stack) to ping `/health` every 5 minutes to keep it awake.

## Docker (Any Provider)

Build and run the registry container:

```bash
# Build
docker build -f registry/Dockerfile -t ace-registry .

# Run
docker run -d \
  -p 9000:9000 \
  -v ace-data:/data \
  --name ace-registry \
  ace-registry
```

## Fly.io

```bash
# Install flyctl
curl -L https://fly.io/install.sh | sh

# Launch
fly launch --dockerfile registry/Dockerfile --name ace-registry

# Deploy
fly deploy
```

## Koyeb

```bash
# Install CLI
curl -fsSL https://raw.githubusercontent.com/koyeb/koyeb-cli/master/install.sh | sh

# Deploy from Docker
koyeb deploy --app ace-registry --docker ace-registry:latest --port 9000
```

## After Deployment

Once your registry is deployed at `https://your-registry.onrender.com`:

```bash
# Initialize agents to use it
ace init --name my-agent \
  --discovery registry \
  --registry-url https://your-registry.onrender.com

# Start with auto-registration
ace start --public
```

## Monitoring

Check your registry's health:

```bash
curl https://your-registry.onrender.com/health
```

Response:

```json
{
  "status": "ok",
  "version": "0.1.0",
  "agent_count": 5,
  "uptime_seconds": 3600.0
}
```
