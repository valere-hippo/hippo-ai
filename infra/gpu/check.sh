#!/usr/bin/env bash
set -euo pipefail

echo '=== HOST GPU ==='
nvidia-smi

echo
echo '=== DOCKER ==='
docker --version
docker compose version

echo
echo '=== NVIDIA RUNTIME ==='
docker info --format '{{json .Runtimes}}'

echo
echo '=== GPU CONTAINER TEST ==='
docker run --rm --gpus all nvidia/cuda:12.6.2-base-ubuntu24.04 nvidia-smi
