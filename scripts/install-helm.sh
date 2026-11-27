#!/usr/bin/env bash
# Install Helm at the version in versions.env (D25), for rendering tenant charts in CI. The laptop has the same
# version already. Helm publishes its binaries only on get.helm.sh, with a checksum file next to each: it catches a
# broken download, not a compromised release (same caveat as Project 4's ci-tools.sh).
#
# Usage: ./scripts/install-helm.sh            -> ~/.local/bin/helm
#        HELM_DIR=/some/bin ./scripts/install-helm.sh   (CI)
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck disable=SC1091  # versions.env: plain KEY=value lines
source versions.env
dest=${HELM_DIR:-$HOME/.local/bin}
name="helm-${HELM_VERSION}-linux-amd64.tar.gz"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
curl -sSfL --retry 3 -o "$work/$name" "https://get.helm.sh/$name"
sum=$(curl -sSfL --retry 3 "https://get.helm.sh/$name.sha256sum" | awk '{print $1}')
echo "$sum  $work/$name" | sha256sum -c --quiet - || { echo "FAIL $name does not match its checksum"; exit 1; }
tar -xzf "$work/$name" -C "$work" linux-amd64/helm
mkdir -p "$dest"
install -m 0755 "$work/linux-amd64/helm" "$dest/helm"
echo "OK   helm $("$dest/helm" version --short) in $dest"