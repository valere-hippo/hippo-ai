Déploiement Kubernetes — guide rapide

1) Préparer le cluster
 - Installer un cluster k8s (kubeadm / managed / k3s)
 - Installer NVIDIA device-plugin si GPU: https://github.com/NVIDIA/k8s-device-plugin

2) Installer Harbor
 - Déployer Harbor via Helm (script fourni)
 - Créer un projet et un robot account pour pousser images

3) Secrets GitHub
 - Add secrets.REGISTRY_HOST, REGISTRY_USER, REGISTRY_PASSWORD, KUBECONFIG (base64)

4) Déployer Hippo-AI
 - helm repo add hippo-ai /path/to/chart
 - helm upgrade --install hippo-ai charts/hippo-ai -f charts/hippo-ai/values.yaml

Notes:
 - Update values.yaml with storage endpoints, database connection strings and ingress host.
 - For local-first testing use k3s or minikube.
