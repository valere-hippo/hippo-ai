Deploy via infra runner (docker-compose)

Overview
- The CI workflow builds images and pushes them to GitHub Container Registry (ghcr.io).
- Deployment is now handled by `hippoject-infra` on the Hetzner self-hosted runner.

Required repository secrets (Settings → Secrets → Actions)
- GHCR_TOKEN: Personal Access Token (packages:write, read) or use repo GITHUB_TOKEN for same-repo pushes
- AI_DEPLOY_PATH: path on remote host where the Hippo AI stack lives (working directory)
This document now describes the infra-runner deployment flow; no SSH deploy keys are required for `hippo-ai` itself.

Server preparation (target host)
1. Install Docker and Docker Compose (and nvidia-container-runtime if using GPUs).
2. Create a directory for deployment (e.g., /opt/hippo-ai) and put docker-compose.yml there. The compose should reference images from ghcr.io/<owner>/hippo-ai-api:latest.
3. Ensure the self-hosted runner user can run docker commands.
4. Optionally create a systemd service wrapper for docker-compose for auto start.

Workflow behavior
- On push to master, the workflow will build and push the API image to ghcr.io
- The infra workflow on the Hetzner runner pulls the images, writes the runtime `.env.production`, and runs docker compose up -d

Security notes
- Keep GHCR tokens secret. Use repo-level secrets or organization secrets for shared infra.

If you want, I can generate a recommended docker-compose.yml for the server including services: api, postgres, redis, nginx, gpu-models, with labels and volumes.
