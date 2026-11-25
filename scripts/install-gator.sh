#!/usr/bin/env bash
# Install gator (Gatekeeper's offline test CLI) at the version and sha256 pinned in versions.env (D12).
# The archive is checked before anything is unpacked; a different file stops the script.
#
# Usage: ./scripts/install-gator.sh            -> ~/.local/bin/gator
#        GATOR_DIR=/some/bin ./scripts/install-gator.sh   (CI)
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck disable=SC1091  # versions.env: plain KEY=value lines
source versions.env
dest=${GATOR_DIR:-$HOME/.local/bin}
name="gator-v${GATEKEEPER_VERSION}-linux-amd64.tar.gz"
url="https://github.com/open-policy-agent/gatekeeper/releases/download/v${GATEKEEPER_VERSION}/${name}"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
curl -sSfL --retry 3 -o "$work/$name" "$url"
echo "${GATOR_SHA256}  $work/$name" | sha256sum -c --quiet - || { echo "FAIL $name does not match GATOR_SHA256"; exit 1; }
tar -xzf "$work/$name" -C "$work" gator
mkdir -p "$dest"
install -m 0755 "$work/gator" "$dest/gator"
echo "OK   gator v${GATEKEEPER_VERSION} in $dest ($("$dest/gator" --version 2>&1 | head -1))"