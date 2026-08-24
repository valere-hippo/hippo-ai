Deploy via SSH (docker-compose)

Overview
- The CI workflow builds images and pushes them to GitHub Container Registry (ghcr.io).
- The deploy job SSHes into your target host and runs docker-compose pull && docker-compose up -d.

Required repository secrets (Settings → Secrets → Actions)
- DEPLOY_HOST: target host IP or hostname
- DEPLOY_USER: ssh user for deployment
- DEPLOY_SSH_KEY: private SSH key for DEPLOY_USER (no passphrase), base64 or raw
- DEPLOY_PORT: (optional) SSH port, default 22
- DEPLOY_PATH: path on remote host where the docker-compose.yml lives (working directory)
- GHCR_TOKEN: Personal Access Token (packages:write, read) or use repo GITHUB_TOKEN for same-repo pushes

Server preparation (target host)
1. Install Docker and Docker Compose (and nvidia-container-runtime if using GPUs).
2. Create a directory for deployment (e.g., /opt/hippo-ai) and put docker-compose.yml there. The compose should reference images from ghcr.io/<owner>/hippo-ai-api:latest and hippo-ai-desktop.
3. Ensure the DEPLOY_USER can run docker commands (add to docker group or use sudo in scripts).
4. Optionally create a systemd service wrapper for docker-compose for auto start.

Workflow behavior
- On push to main, the workflow will build and push the images to ghcr.io
- The deploy job will SSH to DEPLOY_HOST, perform docker login to ghcr, pull images, and run docker-compose up -d

Security notes
- Keep GHCR tokens and SSH keys secret. Use repo-level secrets or organization secrets for shared infra.

If you want, I can generate a recommended docker-compose.yml for the server including services: api, postgres, redis, nginx, gpu-models, with labels and volumes.
