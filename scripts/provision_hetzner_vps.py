#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from textwrap import indent

API_ROOT = "https://api.hetzner.cloud/v1"
DNS_API_ROOT = "https://dns.hetzner.com/api/v1"


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def mask(value: str) -> None:
    if value:
        print(f"::add-mask::{value}")


def fail(message: str) -> None:
    raise SystemExit(message)


def request_json(method: str, path: str, token: str, payload: dict | None = None) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{API_ROOT}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def request_dns_json(method: str, path: str, token: str, payload: dict | None = None) -> dict:
    headers = {
        "Auth-API-Token": token,
        "Content-Type": "application/json",
    }
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{DNS_API_ROOT}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def wait_for_backend_health(base_url: str, timeout_seconds: int = 900, interval_seconds: int = 10) -> dict:
    deadline = time.time() + timeout_seconds
    health_url = f"{base_url.rstrip('/')}/health"
    last_error: str | None = None
    while time.time() < deadline:
        try:
            req = urllib.request.Request(health_url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                payload = json.load(resp)
                if isinstance(payload, dict) and payload.get("status") == "ok":
                    return payload
                last_error = f"unexpected payload: {payload!r}"
        except Exception as exc:  # noqa: BLE001 - surface any readiness/network failure
            last_error = str(exc)
        print(f"Waiting for backend health at {health_url} ...")
        time.sleep(interval_seconds)
    fail(f"Backend did not become healthy within {timeout_seconds}s: {last_error or 'unknown error'}")


def write_github_output(**values: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as fh:
        for key, value in values.items():
            fh.write(f"{key}={value}\n")


def upsert_dns_a_record(token: str, zone_id: str, record_name: str, ip_address: str, ttl: int = 300) -> dict:
    records_payload = request_dns_json("GET", f"/records?zone_id={urllib.parse.quote(zone_id)}", token)
    records = records_payload.get("records", []) if isinstance(records_payload, dict) else []
    existing = next(
        (
            record
            for record in records
            if record.get("type") == "A" and record.get("name") == record_name
        ),
        None,
    )
    payload = {
        "zone_id": zone_id,
        "type": "A",
        "name": record_name,
        "value": ip_address,
        "ttl": ttl,
    }
    if existing and existing.get("id"):
        return request_dns_json("PUT", f"/records/{existing['id']}", token, payload)
    return request_dns_json("POST", "/records", token, payload)


def build_nginx_conf(public_hostname: str) -> str:
    return """server {{
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name {public_hostname} _;

    client_max_body_size 50m;

    location / {{
        proxy_pass http://api:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 900;
        proxy_connect_timeout 60;
        proxy_send_timeout 900;
    }}
}}
""".format(public_hostname=public_hostname)


def main() -> int:
    token = env("HCLOUD_TOKEN")
    if not token:
        fail("HCLOUD_TOKEN is missing.")

    provider = env("INPUT_PROVIDER").lower()
    api_key = env("INPUT_API_KEY")
    server_name = env("INPUT_SERVER_NAME") or "hippo-ai-prod"
    server_type = env("HCLOUD_SERVER_TYPE") or env("INPUT_SERVER_TYPE") or "cpx31"
    location = env("HCLOUD_LOCATION") or env("INPUT_LOCATION") or "nbg1"
    image = env("HCLOUD_IMAGE") or env("INPUT_IMAGE") or "ubuntu-24.04"
    hippo_ai_base_url = env("HIPPO_AI_BASE_URL") or env("INPUT_HIPPO_AI_BASE_URL")
    hippo_ai_model = env("HIPPO_AI_MODEL") or env("INPUT_HIPPO_AI_MODEL")
    pcloud_access_token = env("PCLOUD_ACCESS_TOKEN")
    ssh_key_id = env("HCLOUD_SSH_KEY_ID")
    ssh_key_name = env("HCLOUD_SSH_KEY_NAME")
    owner = env("GITHUB_REPOSITORY_OWNER")

    public_hostname = env("HIPPO_PUBLIC_HOSTNAME") or env("INPUT_PUBLIC_HOSTNAME") or "hippo-api.hipposideros-cloud.de"
    dns_zone_id = env("HETZNER_DNS_ZONE_ID") or env("INPUT_DNS_ZONE_ID")
    dns_record_name = env("HETZNER_DNS_RECORD_NAME") or env("INPUT_DNS_RECORD_NAME") or public_hostname.split(".")[0]
    dns_token = env("HETZNER_DNS_TOKEN")
    dns_ttl_raw = env("HETZNER_DNS_TTL") or env("INPUT_DNS_TTL") or "300"
    dns_ttl: int = 300
    try:
        dns_ttl = int(dns_ttl_raw)
    except ValueError:
        fail(f"Invalid DNS TTL: {dns_ttl_raw}")

    if provider not in {"openai", "claude"}:
        fail(f"Unsupported provider: {provider}")
    if not api_key:
        fail("API key input is missing.")
    if not hippo_ai_base_url:
        fail("HIPPO_AI_BASE_URL is missing. Set the repo variable or pass the workflow input.")
    if not hippo_ai_model:
        fail("HIPPO_AI_MODEL is missing. Set the repo variable or pass the workflow input.")
    if not owner:
        fail("GITHUB_REPOSITORY_OWNER is missing.")
    if not dns_token or not dns_zone_id:
        fail("Hetzner DNS config is missing. Set HETZNER_DNS_TOKEN and HETZNER_DNS_ZONE_ID.")

    postgres_password = secrets.token_urlsafe(32)
    jwt_secret = secrets.token_urlsafe(48)
    openai_api_key = api_key if provider == "openai" else ""
    anthropic_api_key = api_key if provider == "claude" else ""

    mask(api_key)
    mask(postgres_password)
    mask(jwt_secret)
    mask(pcloud_access_token)
    mask(dns_token)

    if not ssh_key_id and ssh_key_name:
        query = urllib.parse.urlencode({"name": ssh_key_name})
        response = request_json("GET", f"/ssh_keys?{query}", token)
        matches = [item for item in response.get("ssh_keys", []) if item.get("name") == ssh_key_name]
        if not matches:
            fail(f"Hetzner SSH key named '{ssh_key_name}' was not found.")
        ssh_key_id = str(matches[0]["id"])

    env_lines = [
        "APP_ENV=production",
        "POSTGRES_DB=hippo_ai",
        "POSTGRES_USER=hippo",
        f"POSTGRES_PASSWORD={postgres_password}",
        f"JWT_SECRET_KEY={jwt_secret}",
        f"HIPPO_AI_BASE_URL={hippo_ai_base_url}",
        f"HIPPO_AI_MODEL={hippo_ai_model}",
        f"MODEL_PROVIDER={provider}",
        f"OPENAI_API_KEY={openai_api_key}",
        f"ANTHROPIC_API_KEY={anthropic_api_key}",
        "PCLOUD_API_BASE_URL=https://eapi.pcloud.com",
        f"PCLOUD_ACCESS_TOKEN={pcloud_access_token}",
    ]

    nginx_conf = build_nginx_conf(public_hostname)
    compose_file = f"""version: '3.8'
services:
  postgres:
    image: postgres:17
    restart: always
    env_file: .env
    volumes:
      - hippo_postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: [\"CMD-SHELL\", \"pg_isready -U hippo -d hippo_ai\"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:8-alpine
    restart: always
    volumes:
      - hippo_redis_data:/data

  api:
    image: ghcr.io/{owner}/hippo-ai-api:latest
    restart: always
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started

  nginx:
    image: nginx:stable-alpine
    restart: always
    depends_on:
      - api
    ports:
      - \"80:80\"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro

volumes:
  hippo_postgres_data:
  hippo_redis_data:
"""

    cloud_config = f"""#cloud-config
package_update: true
package_upgrade: true
packages:
  - ca-certificates
  - curl
  - git
  - jq
  - docker.io
  - docker-compose-plugin

bootcmd:
  - mkdir -p /opt/hippo-stack

write_files:
  - path: /opt/hippo-stack/.env
    permissions: '0600'
    content: |
{indent(os.linesep.join(env_lines), '      ')}
  - path: /opt/hippo-stack/docker-compose.yml
    permissions: '0644'
    content: |
{indent(compose_file.rstrip(), '      ')}
  - path: /opt/hippo-stack/nginx.conf
    permissions: '0644'
    content: |
{indent(nginx_conf.rstrip(), '      ')}

runcmd:
  - systemctl enable --now docker
  - [ bash, -lc, 'cd /opt/hippo-stack && docker compose pull' ]
  - [ bash, -lc, 'cd /opt/hippo-stack && docker compose up -d' ]
"""

    payload: dict[str, object] = {
        "name": server_name,
        "server_type": server_type,
        "image": image,
        "location": location,
        "user_data": cloud_config,
    }
    if ssh_key_id:
        payload["ssh_keys"] = [int(ssh_key_id)]

    result: dict = {}
    try:
        result = request_json("POST", "/servers", token, payload)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        fail(f"Hetzner server creation failed ({exc.code}): {body}")

    server = result.get("server", {})
    public_net = server.get("public_net", {}) or {}
    ipv4 = public_net.get("ipv4", {}) or {}
    ipv6 = public_net.get("ipv6", {}) or {}

    server_id = server.get("id")
    server_status = server.get("status")
    server_ipv4 = ipv4.get("ip")
    server_ipv6 = ipv6.get("ip")

    if not server_ipv4:
        fail("Hetzner server did not return an IPv4 address.")

    ip_backend_url = f"http://{server_ipv4}"
    wait_for_backend_health(ip_backend_url)

    dns_result = upsert_dns_a_record(dns_token, dns_zone_id, dns_record_name, str(server_ipv4), ttl=dns_ttl)
    public_backend_url = f"http://{public_hostname}"
    wait_for_backend_health(public_backend_url)

    write_github_output(
        server_id=str(server_id or ""),
        server_ipv4=str(server_ipv4),
        backend_url=public_backend_url,
        provider=provider,
        public_hostname=public_hostname,
    )

    print("Created Hetzner server")
    print(f"- id: {server_id}")
    print(f"- name: {server_name}")
    print(f"- status: {server_status}")
    print(f"- ipv4: {server_ipv4}")
    if server_ipv6:
        print(f"- ipv6: {server_ipv6}")
    print(f"- provider: {provider}")
    print(f"- dns_record: {dns_record_name}")
    print(f"- public_hostname: {public_hostname}")
    print(f"- backend_url: {public_backend_url}")
    print(f"- dns_result: {dns_result}")

    summary = [
        "## Hetzner VPS created",
        f"- Server ID: `{server_id}`",
        f"- Name: `{server_name}`",
        f"- IPv4: `{server_ipv4}`",
        f"- Provider: `{provider}`",
        f"- Public hostname: `{public_hostname}`",
        f"- Desktop/backend URL: `{public_backend_url}`",
        f"- Health check: `ok`",
        "",
        "### Runtime config written on the VPS",
        f"- `HIPPO_AI_BASE_URL` = `{hippo_ai_base_url}`",
        f"- `HIPPO_AI_MODEL` = `{hippo_ai_model}`",
        f"- `MODEL_PROVIDER` = `{provider}`",
        f"- `DNS record` = `{dns_record_name}`",
    ]
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
        fh.write("\n".join(summary) + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
