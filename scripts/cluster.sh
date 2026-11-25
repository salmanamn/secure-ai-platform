#!/usr/bin/env bash
# The laptop cluster (D11): a minikube profile with the Kubernetes version, CPUs and memory from versions.env,
# Calico (NetworkPolicy, M2) and metrics-server.
#
# Usage: ./scripts/cluster.sh up | stop | delete | status
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck disable=SC1091  # versions.env: plain KEY=value lines
source versions.env

case "${1:-}" in
  up)
    minikube start -p "$MINIKUBE_PROFILE" --kubernetes-version="$KUBERNETES_VERSION" --cni=calico \
      --cpus="$MINIKUBE_CPUS" --memory="$MINIKUBE_MEMORY" --addons=metrics-server
    kubectl config use-context "$MINIKUBE_PROFILE" >/dev/null
    kubectl wait --for=condition=Ready nodes --all --timeout=180s >/dev/null
    kubectl -n kube-system rollout status daemonset/calico-node --timeout=300s >/dev/null
    echo "OK   cluster $MINIKUBE_PROFILE: $(kubectl version -o json | jq -r .serverVersion.gitVersion), calico ready"
    ;;
  stop)
    minikube stop -p "$MINIKUBE_PROFILE"
    ;;
  delete)
    minikube delete -p "$MINIKUBE_PROFILE"
    ;;
  status)
    minikube status -p "$MINIKUBE_PROFILE" || true
    kubectl --context "$MINIKUBE_PROFILE" get nodes -o wide
    ;;
  *)
    echo "usage: $0 up | stop | delete | status" >&2
    exit 2
    ;;
esac