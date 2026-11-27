"""Policy must fail: weaken the policy one way at a time and require the tests to catch each one (D5).

Each mutation removes one promise the policy makes: Deployments, CronJobs and init containers are judged; images come
from the allowed registries with a version that is not latest; containers request CPU and memory and limit memory;
pods mount no API token; tenant namespaces carry their owner and Pod Security "restricted" for all three modes; only
platform namespaces are exempt; tenant namespaces are not excluded; constraints deny (M1). Tenant network policies
stay inside the tenant; tenant role bindings grant the tenant roles to that tenant only; the tenant admin role reads
no Secrets and writes no network policies; every tenant starts closed, with no LoadBalancer or NodePort Services and
no default resources (M2). A live check refuses a cluster that isn't answering (D21); a tenant admits only its own
pods and named platform namespaces (D24); KEDA reads no tenant's Secrets and the webhook skips it (D22); a tenant
release is pinned, stays in its range, renders no Secret or exposed Service, keeps secret settings out of
ConfigMaps, and fits its quota (D25-D27) (M3).

The script works on a temporary copy of the repository (tracked and new files, not ignored ones), regenerates the
templates and the tenancy objects there (scripts/build_policy.py, scripts/build_platform.py), and runs the unit tests
(the policy through regopy) and the gator suite when gator is on PATH.
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
NETPOL = f"{RULES}/tenant-network-policy/rule.rego"
BINDING = f"{RULES}/tenant-role-binding/rule.rego"
ROLES = "platform/cluster/roles.yaml"
BUILD = "scripts/build_platform.py"
RELEASE = "platform/releases/triage.yaml"
RENDERED = "platform/rendered/triage.yaml"


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
    # M2: the two tenancy rules
    Mutation("ingress-from-other-namespaces", NETPOL, "    not allowed_ingress(peer)\n", "    false\n"),
    Mutation("egress-rule-without-peers", NETPOL, '    count(object.get(rule, "to", [])) == 0\n', "    false\n"),
    Mutation(
        "egress-to-any-namespace",
        NETPOL,
        "    peer.namespaceSelector.matchLabels[name_key] in input.parameters.egressNamespaces\n",
        "",
    ),
    Mutation("egress-to-any-range", NETPOL, "    peer.ipBlock.cidr in tenant_cidrs\n", ""),
    Mutation(
        "ranges-shared-between-tenants",
        NETPOL,
        'tenant_cidrs := object.get(object.get(input.parameters, "egressCIDRs", {}), namespace, [])',
        "tenant_cidrs := [c | some cs in input.parameters.egressCIDRs; some c in cs]",
    ),
    Mutation("binding-any-cluster-role", BINDING, "    ref.name in input.parameters.allowedClusterRoles\n", ""),
    Mutation(
        "binding-any-tenant-group",
        BINDING,
        '    startswith(subject.name, sprintf("tenant:%v:", [namespace]))\n',
        '    startswith(subject.name, "tenant:")\n',
    ),
    # M2: the tenancy objects (checked by the unit tests only: gator never sees them)
    Mutation(
        "tenant-admin-reads-secrets",
        ROLES,
        "    resources: [pods, services, configmaps, persistentvolumeclaims]\n",
        "    resources: [pods, services, configmaps, persistentvolumeclaims, secrets]\n",
        engines=("pytest",),
    ),
    Mutation(
        "tenant-admin-writes-network-policies",
        ROLES,
        "    verbs: [get, list, watch, create, update, patch, delete]\n"
        "  - apiGroups: [networking.k8s.io]\n    resources: [networkpolicies]\n    verbs: [get, list, watch]\n",
        "    verbs: [get, list, watch, create, update, patch, delete]\n"
        "  - apiGroups: [networking.k8s.io]\n    resources: [networkpolicies]\n"
        "    verbs: [get, list, watch, create, update, patch, delete]\n",
        engines=("pytest",),
    ),
    Mutation("default-deny-dropped", BUILD, "        default_deny(tenant),\n", "", engines=("pytest",)),
    Mutation(
        "limit-range-defaults",
        BUILD,
        '"spec": {"limits": [{"type": "Container", "max": maximum}]},',
        '"spec": {"limits": [{"type": "Container", "max": maximum, "default": maximum}]},',
        engines=("pytest",),
    ),
    Mutation(
        "node-ports-allowed",
        BUILD,
        'hard |= {"services.loadbalancers": "0", "services.nodeports": "0"}',
        'hard |= {"services.loadbalancers": "0"}',
        engines=("pytest",),
    ),
    Mutation(
        "tenant-groups-cross-namespaces",
        BUILD,
        "f\"tenant:{tenant['name']}:{group}\"",
        'f"tenant:triage:{group}"',
        engines=("pytest",),
    ),
    # M3: tenant ingress from platform namespaces only (D24)
    Mutation(
        "ingress-from-any-named-namespace",
        NETPOL,
        "    peer.namespaceSelector.matchLabels[name_key] in input.parameters.ingressNamespaces\n",
        "",
    ),
    # M3: KEDA (D22) and the triage release (D25-D27), checked by the unit tests on the committed files
    Mutation(
        "keda-reads-tenant-secrets",
        "platform/keda/values.yaml",
        "  operator:\n    restrict:\n      secret: true\n",
        "  operator:\n    restrict:\n      secret: false\n",
        engines=("pytest",),
    ),
    Mutation(
        "keda-not-exempt-from-webhook",
        "platform/gatekeeper/values.yaml",
        "exemptNamespaces: [kube-system, keda]",
        "exemptNamespaces: [kube-system]",
        engines=("pytest",),
    ),
    Mutation(
        "release-on-a-branch",
        RELEASE,
        '  ref: "',
        '  ref: "main" # "',
        engines=("pytest",),
    ),
    Mutation(
        "release-egress-anywhere",
        RENDERED,
        "cidr: 192.168.58.96/28",
        "cidr: 0.0.0.0/0",
        engines=("pytest",),
    ),
    Mutation(
        "release-secret-in-configmap",
        RENDERED,
        '  QUEUE_DEPTH_ENDPOINT: "true"\n',
        '  QUEUE_DEPTH_ENDPOINT: "true"\n  COSMOS_KEY: "leaked"\n',
        engines=("pytest",),
    ),
    Mutation(
        "release-renders-a-secret",
        RENDERED,
        "# helm: v4.3.2\n",
        "# helm: v4.3.2\n---\napiVersion: v1\nkind: Secret\nmetadata:\n  name: leaked\n  namespace: triage\n",
        engines=("pytest",),
    ),
    Mutation(
        "release-nodeport",
        RENDERED,
        "  type: ClusterIP\n  selector:\n    app.kubernetes.io/name: ticket-triage\n"
        "    app.kubernetes.io/instance: triage\n    app.kubernetes.io/component: lab-llm\n",
        "  type: NodePort\n  selector:\n    app.kubernetes.io/name: ticket-triage\n"
        "    app.kubernetes.io/instance: triage\n    app.kubernetes.io/component: lab-llm\n",
        engines=("pytest",),
    ),
    Mutation(
        "triage-quota-without-headroom",
        "platform/tenants.yaml",
        '(D27, tests/unit/test_releases.py)\n      requests.cpu: "1"\n      requests.memory: 2Gi\n'
        "      limits.memory: 4Gi\n",
        '(D27, tests/unit/test_releases.py)\n      requests.cpu: "1"\n      requests.memory: 2Gi\n'
        "      limits.memory: 3Gi\n",
        engines=("pytest",),
    ),
    # M3: evidence only from a cluster that answered (D21)
    Mutation(
        "readiness-not-checked",
        "scripts/cluster_ready.py",
        '    if result.returncode == 0 and result.stdout.strip() == "ok":\n',
        "    if True:\n",
        engines=("pytest",),
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
    for script in ("scripts/build_policy.py", "scripts/build_platform.py"):
        build = subprocess.run([sys.executable, script], cwd=workdir, capture_output=True, text=True)
        if build.returncode != 0:
            return {"build": False}
    results = {}
    pytest = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/unit"],
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
