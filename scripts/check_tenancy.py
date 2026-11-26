"""Tenant isolation on a live cluster (D20): roles, quotas and limits, network policy, ephemeral containers.

uv run python scripts/check_tenancy.py [--context NAME] [--evidence docs/evidence/m2-tenancy.txt] [--only SECTION]

Sections (all by default; --only rbac|admission|network|debug):
- rbac       every row of platform/checks/rbac-matrix.yaml with `kubectl auth can-i --as <user> --as-group <group>`
- admission  platform/checks/admission/*.yaml through `kubectl apply --dry-run=server`: allowed-* must be admitted,
             denied-* refused by the quota or the limit range (their message matches the case's expectation), and by
             nothing of Gatekeeper's
- network    probe pods in triage and voice (a python image from an allowed registry, Pod Security restricted):
             round 1 = the platform baseline (DNS only); then platform/checks/netpol-probe-allow.yaml opens one flow
             in triage, and round 2 checks that flow and that nothing else opened
- debug      `kubectl debug --profile=restricted` adds an ephemeral container to a probe pod: from docker.io it must
             be refused by platform-allowed-images, from the allowed registry admitted (D6)

Every line: OK or FAIL, what, expected, seen. Exit 1 when any line is FAIL. Probe pods and the allow policy are
deleted at the end. Evidence names users, namespaces and flows only (no `@`).
"""

import argparse
import datetime
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CHECKS = ROOT / "platform" / "checks"
EXPECT = "test.platform.lab/expect"
PROBE_IMAGE = "mcr.microsoft.com/azurelinux/base/python:3.12.16-2-azl3.0.20261120"  # has python3, no `python`
DEBUG_DENIED_IMAGE = "docker.io/library/busybox:1.37"
CONNECT = (
    "import socket,sys\n"
    "try:\n socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=3).close(); print('open')\n"
    "except OSError: print('closed')"
)
RESOLVE = (
    "import socket,sys\ntry:\n socket.getaddrinfo(sys.argv[1], 443); print('resolved')\nexcept OSError: print('failed')"
)


def parse_resource(text: str) -> tuple[str, str]:
    """kubectl's TYPE[.GROUP] or TYPE/SUBRESOURCE -> (group, resource): deployments.apps -> (apps, deployments)."""
    if "/" in text:
        return "", text  # core-group subresources only (pods/exec, pods/log, ...)
    resource, _, group = text.partition(".")
    return group, resource


def load_matrix(path: Path = CHECKS / "rbac-matrix.yaml") -> tuple[dict, list[tuple]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data["subjects"], [tuple(row) for row in data["checks"]]


def kubectl(context: str | None, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    base = ["kubectl", *(["--context", context] if context else [])]
    return subprocess.run([*base, *args], capture_output=True, text=True, check=False, input=stdin)


def line(ok: bool, what: str, expected: str, seen: str) -> str:
    return f"{'OK  ' if ok else 'FAIL'} {what}: expected {expected}, seen {seen}"


def check_rbac(context: str | None) -> list[str]:
    subjects, rows = load_matrix()
    lines = []
    for name, verb, resource, namespace, allowed in rows:
        subject = subjects[name]
        args = ["auth", "can-i", verb, resource, "--as", subject["user"]]
        args += [f"--as-group={g}" for g in subject["groups"]]
        if namespace:
            args += ["-n", namespace]
        seen = kubectl(context, *args).stdout.strip() or "error"
        want = "yes" if allowed else "no"
        where = namespace or "cluster"
        lines.append(line(seen == want, f"rbac {name} {verb} {resource} in {where}", want, seen))
    return lines


def admission_verdict(name: str, expect: str | None, returncode: int, output: str) -> tuple[bool, str]:
    if name.startswith("allowed-"):
        return (returncode == 0, "admitted" if returncode == 0 else "denied")
    if returncode == 0:
        return False, "admitted"
    if "validation.gatekeeper.sh" in output:
        return False, "denied by Gatekeeper"
    if expect and re.search(expect, output):
        return True, "denied as expected"
    return False, "denied for another reason"


def check_admission(context: str | None) -> list[str]:
    lines = []
    for path in sorted((CHECKS / "admission").glob("*.yaml")):
        obj = yaml.safe_load(path.read_text(encoding="utf-8"))
        expect = (obj["metadata"].get("annotations") or {}).get(EXPECT)
        result = kubectl(context, "apply", "--dry-run=server", "-f", str(path))
        ok, seen = admission_verdict(path.stem, expect, result.returncode, result.stdout + result.stderr)
        want = "admitted" if path.stem.startswith("allowed-") else "denied as expected"
        lines.append(line(ok, f"admission {path.stem}", want, seen))
    return lines


def probe_manifest(namespace: str, name: str, role: str) -> str:
    pod = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": name, "namespace": namespace, "labels": {"platform.lab/probe": role}},
        "spec": {
            "automountServiceAccountToken": False,
            "securityContext": {"runAsNonRoot": True, "runAsUser": 65532, "seccompProfile": {"type": "RuntimeDefault"}},
            "containers": [
                {
                    "name": "probe",
                    "image": PROBE_IMAGE,
                    # runs in the probe pod, not here: listen on the pod's address, serve an empty directory
                    "command": ["python3", "-m", "http.server", "8080", "--bind", "0.0.0.0", "--directory", "/tmp"],  # noqa: S104, S108
                    "securityContext": {
                        "allowPrivilegeEscalation": False,
                        "readOnlyRootFilesystem": True,
                        "capabilities": {"drop": ["ALL"]},
                    },
                    "resources": {"requests": {"cpu": "10m", "memory": "32Mi"}, "limits": {"memory": "64Mi"}},
                }
            ],
        },
    }
    return yaml.safe_dump(pod)


PROBES = {"triage/client": "client", "triage/server": "server", "voice/client": "client"}


def start_probes(context: str | None) -> dict[str, str]:
    """Probe pods (each runs a small HTTP server on 8080); returns their pod IPs."""
    for key, role in PROBES.items():
        namespace, name = key.split("/")
        kubectl(context, "-n", namespace, "delete", "pod", f"probe-{name}", "--ignore-not-found", "--wait=true")
        created = kubectl(context, "apply", "-f", "-", stdin=probe_manifest(namespace, f"probe-{name}", role))
        if created.returncode != 0:
            raise SystemExit(f"probe {key} refused: {created.stderr.strip()}")
    ips = {}
    for key in PROBES:
        namespace, name = key.split("/")
        waited = kubectl(
            context, "-n", namespace, "wait", "--for=condition=Ready", f"pod/probe-{name}", "--timeout=180s"
        )
        if waited.returncode != 0:
            raise SystemExit(f"probe {key} not ready: {waited.stderr.strip()}")
        ips[key] = kubectl(
            context, "-n", namespace, "get", "pod", f"probe-{name}", "-o", "jsonpath={.status.podIP}"
        ).stdout
    time.sleep(3)  # policies for a new pod are programmed a moment after it is Ready
    return ips


def run_in(context: str | None, key: str, code: str, *args: str) -> str:
    namespace, name = key.split("/")
    result = kubectl(context, "-n", namespace, "exec", f"probe-{name}", "--", "python3", "-c", code, *args)
    return result.stdout.strip() or "error"


def flows(context: str | None, ips: dict[str, str], dns_ip: str, api_ip: str, allow_applied: bool) -> list[str]:
    phase = "round 2 (allow applied)" if allow_applied else "round 1 (baseline)"
    plan = [  # (from, label, host, port, expected)
        ("triage/client", "triage/server:8080", ips["triage/server"], 8080, "open" if allow_applied else "closed"),
        ("voice/client", "triage/server:8080", ips["triage/server"], 8080, "closed"),
        ("triage/server", "triage/client:8080", ips["triage/client"], 8080, "closed"),
    ]
    if not allow_applied:
        plan += [
            ("triage/client", "voice/client:8080", ips["voice/client"], 8080, "closed"),
            ("triage/client", "kube-dns:53", dns_ip, 53, "open"),
            ("triage/client", "kube-api:443", api_ip, 443, "closed"),
            ("triage/client", "outside 1.1.1.1:443", "1.1.1.1", 443, "closed"),
            ("voice/client", "outside 1.1.1.1:443", "1.1.1.1", 443, "closed"),
        ]
    lines = []
    for source, label, host, port, want in plan:
        seen = run_in(context, source, CONNECT, host, str(port))
        lines.append(line(seen == want, f"network {phase} {source} -> {label}", want, seen))
    if not allow_applied:
        seen = run_in(context, "triage/client", RESOLVE, "kubernetes.default.svc.cluster.local")
        lines.append(line(seen == "resolved", f"network {phase} triage/client dns lookup", "resolved", seen))
    return lines


def check_network(context: str | None) -> list[str]:
    allow = CHECKS / "netpol-probe-allow.yaml"
    ips = start_probes(context)
    dns_ip = kubectl(context, "-n", "kube-system", "get", "svc", "kube-dns", "-o", "jsonpath={.spec.clusterIP}").stdout
    api_ip = kubectl(context, "-n", "default", "get", "svc", "kubernetes", "-o", "jsonpath={.spec.clusterIP}").stdout
    lines = flows(context, ips, dns_ip, api_ip, allow_applied=False)
    applied = kubectl(context, "apply", "-f", str(allow))
    if applied.returncode != 0:
        return [*lines, line(False, "network allow policy applied", "applied", applied.stderr.strip())]
    time.sleep(5)
    lines += flows(context, ips, dns_ip, api_ip, allow_applied=True)
    kubectl(context, "delete", "-f", str(allow), "--ignore-not-found")
    return lines


def check_debug(context: str | None) -> list[str]:
    lines = []
    for name, image, want in (
        ("debug-denied", DEBUG_DENIED_IMAGE, "denied by platform-allowed-images"),
        ("debug-allowed", PROBE_IMAGE, "admitted"),
    ):
        result = kubectl(
            context,
            "-n",
            "triage",
            "debug",
            "probe-server",
            f"--image={image}",
            "--profile=restricted",
            f"--container={name}",
            "--",
            "true",
        )
        output = result.stdout + result.stderr
        if result.returncode == 0:
            seen = "admitted"
        elif "[platform-allowed-images]" in output:
            seen = "denied by platform-allowed-images"
        else:
            seen = "denied for another reason"
        lines.append(line(seen == want, f"debug ephemeral container from {image.split('/')[0]}", want, seen))
    return lines


def cleanup(context: str | None) -> None:
    for key in PROBES:
        namespace, name = key.split("/")
        kubectl(context, "-n", namespace, "delete", "pod", f"probe-{name}", "--ignore-not-found", "--wait=false")


SECTIONS = {"rbac": check_rbac, "admission": check_admission, "network": check_network, "debug": check_debug}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--context", help="kubectl context (default: the current one)")
    parser.add_argument("--only", choices=sorted(SECTIONS), help="run one section")
    parser.add_argument("--evidence", type=Path, help="also write the result to this file")
    args = parser.parse_args()
    current = kubectl(args.context, "config", "current-context").stdout.strip()
    lines = [f"date: {datetime.datetime.now(datetime.UTC):%Y-%m-%dT%H:%MZ}", f"context: {args.context or current}"]
    names = [args.only] if args.only else list(SECTIONS)
    if "debug" in names and "network" not in names:
        try:
            start_probes(args.context)  # debug needs a running probe pod
        except SystemExit as stop:
            lines.append(line(False, "debug section", "a running probe pod", str(stop)))
            names.remove("debug")
    try:
        for name in names:
            try:
                section = SECTIONS[name](args.context)
            except SystemExit as stop:
                # a probe that can't start fails its section, and the evidence still gets written
                section = [line(False, f"{name} section", "completed", str(stop))]
            lines += section
            print("\n".join(section), flush=True)
    finally:
        if {"network", "debug"} & set(names):
            cleanup(args.context)
    checks = [entry for entry in lines if entry.startswith(("OK", "FAIL"))]
    failures = sum(entry.startswith("FAIL") for entry in checks)
    summary = (
        f"{len(checks) - failures}/{len(checks)} checks as expected"
        if not failures
        else f"FAIL {failures} of {len(checks)}"
    )
    lines.append(summary)
    print(summary)
    if args.evidence:
        args.evidence.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {args.evidence}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
