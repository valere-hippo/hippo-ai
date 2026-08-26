#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -eq 0 ]]; then SUDO=""; else SUDO="sudo"; fi

if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "ERROR: nvidia-smi is not available. Do not install a driver automatically on GPUHub yet."
  echo "The GPUHub image should provide the NVIDIA driver. Verify the host first."
  exit 1
fi

if ! nvidia-smi >/dev/null 2>&1; then
  echo "ERROR: NVIDIA driver is present but the GPU is not accessible."
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Installing Docker..."
  curl -fsSL https://get.docker.com | $SUDO sh
  $SUDO systemctl enable --now docker
fi

if ! command -v nvidia-ctk >/dev/null 2>&1; then
  echo "Installing NVIDIA Container Toolkit..."
  $SUDO apt-get update
  $SUDO apt-get install -y --no-install-recommends ca-certificates curl gnupg2
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | $SUDO gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
    | $SUDO tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
  $SUDO apt-get update
  $SUDO apt-get install -y nvidia-container-toolkit
fi

$SUDO nvidia-ctk runtime configure --runtime=docker
$SUDO systemctl restart docker

$SUDO docker run --rm --gpus all nvidia/cuda:12.6.2-base-ubuntu24.04 nvidia-smi

echo "GPU container runtime is ready."
