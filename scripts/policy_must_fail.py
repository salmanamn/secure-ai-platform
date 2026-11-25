"""Policy must fail: weaken the policy one way at a time and require the tests to catch each one (D5).

Each mutation removes one promise the policy makes: Deployments, CronJobs and init containers are judged; images come
from the allowed registries with a version that is not latest; containers request CPU and memory and limit memory;
pods mount no API token; tenant namespaces carry their owner and Pod Security "restricted" for all three modes; only
platform namespaces are exempt; tenant namespaces are not excluded; constraints deny.

The script works on a temporary copy of the repository (tracked and new files, not ignored ones), regenerates the
templates there (scripts/build_policy.py) and runs the case tests with regopy, and with gator when it is on PATH.
A mutation must turn every engine it names red. Exit 1 when a mutation survives (add a case), when its anchor text is
not in the file exactly once (update the mutation together with the policy), or when the clean copy fails.

Usage: uv run python scripts/policy_must_fail.py [--only NAME] [--list] [--require-gator]
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = "policy/gatekeeper/lib/workload.rego"
RULES = "policy/gatekeeper/rules"


@dataclass(frozen=True)
class Mutation:
    name: str
    file: str
    old: str
    new: str
    engines: tuple[str, ...] = ("pytest", "gator")


MUTATIONS = [
    Mutation(
        "init-containers-not-judged",
        LIB,
        "containers contains c if {\n    some c in pod_spec.initContainers\n}\n",
        "",
    ),
    Mutation(
        "cronjobs-not-judged",
        LIB,
        'pod_spec := obj.spec.jobTemplate.spec.template.spec if obj.kind == "CronJob"\n',
        "",
    ),
    Mutation(
        "deployments-not-judged",
        LIB,
        'template_kinds := {"Deployment", ',
        "template_kinds := {",
    ),
    Mutation(
        "any-registry",
        f"{RULES}/allowed-images/rule.rego",
        "    not allowed_registry(c.image)\n",
        "    not true\n",
    ),
    Mutation(
        "latest-allowed",
        f"{RULES}/allowed-images/rule.rego",
        '    tag != "latest"\n',
        "",
    ),
    Mutation(
        "untagged-allowed",
        f"{RULES}/allowed-images/rule.rego",
        'pinned(image) if contains(last_segment(image), "@sha256:")\n',
        'pinned(image) if contains(last_segment(image), "@sha256:")\n\n'
        'pinned(image) if not contains(last_segment(image), ":")\n',
    ),
    Mutation(
        "memory-limit-not-required",
        f"{RULES}/container-resources/rule.rego",
        ', ["limits", "memory"]]',
        "]",
    ),
    Mutation(
        "token-only-refused-when-true",
        f"{RULES}/no-sa-token/rule.rego",
        "    not spec.automountServiceAccountToken == false\n",
        "    spec.automountServiceAccountToken == true\n",
    ),
    Mutation(
        "owner-label-not-required",
        f"{RULES}/tenant-namespace/rule.rego",
        'required_labels := {"platform.lab/tenant", "platform.lab/owner"}',
        'required_labels := {"platform.lab/tenant"}',
    ),
    Mutation(
        "pod-security-enforce-only",
        f"{RULES}/tenant-namespace/rule.rego",
        'psa_modes := {"enforce", "warn", "audit"}',
        'psa_modes := {"enforce"}',
    ),
    Mutation(
        "pod-security-any-level",
        f"{RULES}/tenant-namespace/rule.rego",
        '    object.get(labels, key, "") != "restricted"\n',
        '    object.get(labels, key, "") == ""\n',
    ),
    Mutation(
        "every-namespace-exempt",
        f"{RULES}/tenant-namespace/rule.rego",
        "exempt(name) if name in input.parameters.platformNamespaces",
        'exempt(name) if name != ""',
    ),
    Mutation(
        "tenant-namespace-excluded",
        f"{RULES}/allowed-images/constraint.yaml",
        "      - kube-system\n",
        "      - kube-system\n      - triage\n",
    ),
    Mutation(
        "constraint-dry-run",
        f"{RULES}/container-resources/constraint.yaml",
        "enforcementAction: deny",
        "enforcementAction: dryrun",
        engines=("pytest",),  # gator reports violations whatever the action; the unit test checks the action
    ),
]


def repo_files() -> list[Path]:
    """Tracked and new files (not ignored ones), or every file outside .venv/.git before the first commit."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return [Path(line) for line in out.splitlines() if (ROOT / line).is_file()]
    except (OSError, subprocess.CalledProcessError):
        skip = {".venv", ".git", ".pytest_cache", ".ruff_cache", "__pycache__"}
        return [p.relative_to(ROOT) for p in ROOT.rglob("*") if p.is_file() and not skip & set(p.parts)]


def copy_repo(target: Path) -> None:
    for rel in repo_files():
        (target / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, target / rel)


def run_engines(workdir: Path, gator: str | None) -> dict[str, bool]:
    """Regenerate the templates, then run each engine; True means the engine passed (all cases as expected)."""
    build = subprocess.run([sys.executable, "scripts/build_policy.py"], cwd=workdir, capture_output=True, text=True)
    if build.returncode != 0:
        return {"build": False}
    results = {}
    pytest = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/unit/test_policy.py"],
        cwd=workdir,
        capture_output=True,
        text=True,
    )
    results["pytest"] = pytest.returncode == 0
    if gator:
        verify = subprocess.run(
            [gator, "verify", "policy/gatekeeper/suite.yaml"], cwd=workdir, capture_output=True, text=True
        )
        results["gator"] = verify.returncode == 0
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", help="run one mutation by name")
    parser.add_argument("--list", action="store_true", help="list the mutations and exit")
    parser.add_argument("--require-gator", action="store_true", help="fail when gator is not on PATH (CI)")
    args = parser.parse_args()
    if args.list:
        for m in MUTATIONS:
            print(f"{m.name:32} {m.file}  ({', '.join(m.engines)})")
        return 0
    gator = shutil.which("gator")
    if args.require_gator and not gator:
        print("FAIL gator is not on PATH: ./scripts/install-gator.sh")
        return 1
    print(f"engines: pytest (regopy){', gator' if gator else ''}{'' if gator else ' (gator not on PATH)'}")
    selected = [m for m in MUTATIONS if args.only in (None, m.name)]
    if not selected:
        parser.error(f"no mutation named {args.only}")

    failures = 0
    with tempfile.TemporaryDirectory(prefix="policy-must-fail-") as tmp:
        clean = Path(tmp) / "clean"
        copy_repo(clean)
        baseline = run_engines(clean, gator)
        if not all(baseline.values()):
            print(f"FAIL the unmutated copy does not pass: {baseline}")
            return 1
        for m in selected:
            work = Path(tmp) / m.name
            copy_repo(work)
            path = work / m.file
            text = path.read_text(encoding="utf-8")
            if text.count(m.old) != 1:
                print(f"STALE {m.name}: anchor found {text.count(m.old)} times in {m.file}")
                failures += 1
                continue
            path.write_text(text.replace(m.old, m.new), encoding="utf-8")
            results = run_engines(work, gator)
            survived = [e for e in m.engines if results.get(e)]  # an engine that is not installed did not run
            if results.get("build") is False:
                print(f"OK   {m.name}: the generator refused it")
            elif survived:
                print(f"SURVIVED {m.name}: {', '.join(survived)} still pass")
                failures += 1
            else:
                caught = [e for e in m.engines if e in results]
                print(f"OK   {m.name}: caught by {', '.join(caught)}")
            shutil.rmtree(work)
    total = len(selected)
    print(f"{total - failures}/{total} mutations caught" if not failures else f"FAIL {failures} of {total} not caught")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
