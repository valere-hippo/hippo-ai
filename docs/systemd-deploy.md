Systemd service for Docker Compose deployment (auto-start + restart)

Example unit: /etc/systemd/system/hippo-ai.service

[Unit]
Description=Hippo-AI Docker Compose deployment
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/hippo-ai
ExecStart=/usr/bin/docker compose pull
ExecStart=/usr/bin/docker compose up -d --remove-orphans
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=600

[Install]
WantedBy=multi-user.target

Usage:
- Copy docker-compose.prod.yml to /opt/hippo-ai/docker-compose.yml
- Create /opt/hippo-ai/.env with production secrets
- Place hippo-ai.service as above
- Run:
    sudo systemctl daemon-reload
    sudo systemctl enable hippo-ai.service
    sudo systemctl start hippo-ai.service

Autoscaling hints (host-level)
- For horizontal scaling of worker/model nodes, use an orchestration layer (Kubernetes, Nomad). If staying with docker-compose:
  - Provision additional hosts and register them behind a load-balancer.
  - Use CI SSH job to deploy to each host and update Docker Compose replicas (scale worker).
  - Use monitoring (Prometheus + node exporter + nvidia exporter) to trigger autoscaling scripts.

Autoscaling hints (GPU batching / tuning)
- Use model runner config to set batch sizes and concurrency.
- Monitor GPU memory utilization and latency; when high, add nodes; when low, remove nodes.
- Consider using container snapshotting and fast model loading to reduce spin-up time.

Security & maintenance
- Rotate credentials regularly and store secrets in a vault when possible.
- Use a reverse proxy with TLS (nginx + certbot) and enable rate limiting.
- Backup Postgres volume regularly.

I can also generate a small auto-deploy script (deploy.sh) that the CI executes via SSH to perform pull/up and rollout logic (drain workers, restart service). Do you want that script?