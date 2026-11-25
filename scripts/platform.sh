#!/usr/bin/env bash
# Platform components on the current kubectl context (D5, D10).
#
# Usage: ./scripts/platform.sh gatekeeper   Gatekeeper from its Helm chart, version from versions.env
#        ./scripts/platform.sh policy       the generated templates, then the constraints, then wait until enforced
#        ./scripts/platform.sh tenants      the tenant namespaces (admitted by the namespace rule)
#        ./scripts/platform.sh status       templates, constraints and their audit violations
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck disable=SC1091  # versions.env: plain KEY=value lines
source versions.env

constraints=(policy/gatekeeper/rules/*/constraint.yaml)

apply_retry() { # file: a constraint's kind exists a few seconds after its template reports created
  for _ in $(seq 10); do
    kubectl apply -f "$1" >/dev/null 2>&1 && return 0
    sleep 3
  done
  kubectl apply -f "$1" # the last try shows the error
}

wait_enforced() { # kind name: every Gatekeeper pod reports the constraint enforced (up to 2 minutes)
  local kind=$1 name=$2
  for _ in $(seq 60); do
    if kubectl get "$kind" "$name" -o json |
      jq -e '(.status.byPod // []) | length > 0 and all(.enforced == true)' >/dev/null 2>&1; then
      echo "OK   $name enforced"
      return 0
    fi
    sleep 2
  done
  echo "FAIL $name not enforced after 2 minutes: kubectl get $kind $name -o yaml"
  return 1
}

case "${1:-}" in
  gatekeeper)
    helm repo add gatekeeper https://open-policy-agent.github.io/gatekeeper/charts --force-update >/dev/null
    helm upgrade --install gatekeeper gatekeeper/gatekeeper --version "$GATEKEEPER_VERSION" \
      --namespace gatekeeper-system --create-namespace -f platform/gatekeeper/values.yaml --wait --timeout 10m >/dev/null
    for d in gatekeeper-controller-manager gatekeeper-audit; do
      kubectl -n gatekeeper-system rollout status "deploy/$d" --timeout=180s >/dev/null
    done
    echo "OK   gatekeeper $GATEKEEPER_VERSION: $(kubectl get ns kube-system -o jsonpath='{.metadata.labels.admission\.gatekeeper\.sh/ignore}') on kube-system"
    ;;
  policy)
    kubectl apply -f policy/gatekeeper/templates/ >/dev/null
    for t in policy/gatekeeper/templates/*.yaml; do
      name=$(basename "$t" .yaml)
      kubectl wait --for=jsonpath='{.status.created}'=true "constrainttemplate/$name" --timeout=120s >/dev/null
      echo "OK   template $name created"
    done
    for c in "${constraints[@]}"; do
      apply_retry "$c"
    done
    for c in "${constraints[@]}"; do
      kind=$(awk '/^kind:/ {print $2; exit}' "$c")
      name=$(awk '/^  name:/ {print $2; exit}' "$c")
      wait_enforced "${kind,,}" "$name"
    done
    ;;
  tenants)
    kubectl apply -f platform/namespaces/tenants.yaml
    ;;
  status)
    kubectl get constrainttemplates
    kubectl get constraints
    ;;
  *)
    echo "usage: $0 gatekeeper | policy | tenants | status" >&2
    exit 2
    ;;
esac