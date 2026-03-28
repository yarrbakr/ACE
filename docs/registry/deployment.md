# Cloud Deployment

Deploy the ACE registry to a free cloud provider for global access.

## ClawCloud Run (Recommended)

ClawCloud Run offers a free plan ($5/mo credit), always-on containers, and Singapore region.

### Setup

1. Push to GitHub — CI builds and pushes the Docker image to GHCR automatically
2. Go to [ClawCloud dashboard](https://run.claw.cloud) and sign up
3. Click **App Launchpad** > **Create App**
4. Deploy from Docker Image:
   - **Image:** `ghcr.io/yarrbakr/ace-registry:latest`
   - **Port:** `9000`
   - **Env vars:** `PORT=9000`, `ACE_REGISTRY_DB=/tmp/registry.db`
5. After the first deploy, note the assigned URL (e.g., `https://<your-app>.run.claw.cloud`)

!!! note "Manual redeploy"
    ClawCloud does not auto-redeploy when a new image is pushed to GHCR. After CI pushes a new image, click "Redeploy" in the ClawCloud dashboard.

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

## Render

```bash
# Connect your GitHub repo at render.com
# Configure manually:
#   Runtime: Docker
#   Dockerfile: registry/Dockerfile
#   Health Check: /health
```

!!! note "Render free tier sleeps"
    Render's free tier sleeps after 15 minutes of inactivity with ~2 min cold start.

## Public Registry

The official ACE public registry is live at:

```
https://namdvhxjugux.ap-southeast-1.clawcloudrun.com
```

This is the default `registry_url` — no configuration needed. Just run:

```bash
ace init --name my-agent --discovery registry
ace start --public
```

## Monitoring

Check the registry's health:

```bash
curl https://namdvhxjugux.ap-southeast-1.clawcloudrun.com/health
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
