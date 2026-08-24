#!/usr/bin/env bash
set -euo pipefail

HELM_CHART_VERSION="
"# adjust as needed
helm repo add harbor https://helm.goharbor.io
helm repo update

kubectl create ns harbor || true
helm upgrade --install harbor harbor/harbor --namespace harbor \
  --set expose.type=ingress \
  --set persistence.enabled=true \
  --set persistence.persistentVolumeClaim.registry.size=20Gi \
  --set externalURL="https://harbor.example.com"

echo "Harbor install requested — update values for TLS/Storage to match your environment"