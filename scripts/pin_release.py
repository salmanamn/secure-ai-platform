"""Pin a tenant release to the tenant repo's main and the image CI published from it (D25).

uv run python scripts/pin_release.py <tenant>

Reads platform/releases/<tenant>.yaml, asks the tenant repository for its main commit (`git ls-remote`), and the
registry for the digest of `<image.repository>:sha-<first 12 characters>` (the tag the tenant's publish job pushes,
`docker buildx imagetools inspect`: nothing is pulled). Writes both into the release file, nothing else.
Then: uv run python scripts/render_tenants.py, and the tests.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REF = re.compile(r'^(  ref: )"[0-9a-f]{40}"', re.M)  # quoted: an all-digit commit id would read as a number
DIGEST = re.compile(r"^(    digest: )sha256:[0-9a-f]{64}$", re.M)


def run(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"FAIL {' '.join(args[:3])}: {(result.stderr or result.stdout).strip()[-300:]}")
    return result.stdout.strip()


def pinned(text: str, ref: str, digest: str) -> str:
    if len(REF.findall(text)) != 1 or len(DIGEST.findall(text)) != 1:
        raise SystemExit('FAIL the release file needs exactly one `  ref: "<commit>"` line and one `    digest:` line')
    return DIGEST.sub(rf"\g<1>{digest}", REF.sub(rf'\g<1>"{ref}"', text))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tenant")
    args = parser.parse_args()
    path = ROOT / "platform" / "releases" / f"{args.tenant}.yaml"
    text = path.read_text(encoding="utf-8")
    release = yaml.safe_load(text)
    heads = run("git", "ls-remote", release["chart"]["repo"], "refs/heads/main").split()
    if not heads:
        raise SystemExit(f"FAIL {release['chart']['repo']} has no main branch")
    ref = heads[0]
    image = f"{release['values']['image']['repository']}:sha-{ref[:12]}"
    inspect = ["docker", "buildx", "imagetools", "inspect", image, "--format", "{{.Manifest.Digest}}"]
    result = subprocess.run(inspect, capture_output=True, text=True, check=False)
    digest = result.stdout.strip()
    if result.returncode != 0 or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise SystemExit(f"FAIL no image {image} yet (has the publish job for that commit finished?)")
    path.write_text(pinned(text, ref, digest), encoding="utf-8")
    print(f"pinned {args.tenant}: chart at {ref[:12]}, image {image}@{digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
