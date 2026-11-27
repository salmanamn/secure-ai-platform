"""Create a tenant's Secrets on the laptop cluster, as the platform operator (D26).

uv run python scripts/tenant_secrets.py <tenant> [--context NAME] [--rotate]

Tenant admins can't read or write Secrets (D16), and the tenant's chart renders none, so the operator creates
them before the release is applied. For the release in platform/releases/<tenant>.yaml:
- <secretSettings.secretName> in the tenant namespace: the secret app settings the chart reads as env vars. On the
  laptop they are the emulators' published development keys (not secrets, but never in a ConfigMap), pointed at
  the addresses in the release's `lab` block, plus random values for the keys the platform makes up;
- <functionKeys.secretName> in the tenant namespace: the Functions host keys as files (ticket-triage-agent D28),
  random, one per function the release loads, plus the host, KEDA and Event Grid keys;
- <tenant>-queue-depth in keda: KEDA's host key, the same value, for the ClusterTriggerAuthentication.
Existing values are kept, so a re-run changes nothing; --rotate makes new random ones (restart the pods after).
Refuses any context but the laptop cluster's (versions.env MINIKUBE_PROFILE): these values only fit the emulators.
No value is printed, passed on a command line or written to disk: manifests go to kubectl on stdin.
"""

import argparse
import base64
import json
import secrets
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANAGED = {"platform.lab/managed": "true"}
# Published development keys of the emulators (Microsoft's documentation); they only open the emulators.
SERVICEBUS_EMULATOR_KEY = "SAS_KEY_VALUE"
COSMOS_EMULATOR_KEY = "C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw=="
AZURITE_ACCOUNT_KEY = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="
RANDOM = object()


def lab_settings(lab: dict) -> dict[str, object]:
    """Secret settings on the laptop: the emulators at the release's addresses; RANDOM = made up here."""
    return {
        "ServiceBusConnection": (
            f"Endpoint=sb://{lab['servicebus']};SharedAccessKeyName=RootManageSharedAccessKey;"
            f"SharedAccessKey={SERVICEBUS_EMULATOR_KEY};UseDevelopmentEmulator=true;"
        ),
        "COSMOS_KEY": COSMOS_EMULATOR_KEY,
        "AzureWebJobsStorage": (
            f"DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey={AZURITE_ACCOUNT_KEY};"
            f"BlobEndpoint=http://{lab['azurite']}:10000/devstoreaccount1;"
            f"QueueEndpoint=http://{lab['azurite']}:10001/devstoreaccount1;"
            f"TableEndpoint=http://{lab['azurite']}:10002/devstoreaccount1;"
        ),
        "EVENTGRID_TOPIC_KEY": RANDOM,  # the lab Event Grid stub's topic key
        "OPENAI_API_KEY": RANDOM,  # the fake LLM accepts any key
    }


def function_key_names(functions: list[str]) -> list[str]:
    """The files the Functions host reads in read-only Kubernetes mode: it can't create a missing one."""
    names = ["host.master", "host.function.default", "host.function.keda", "host.systemKey.eventgrid_extension"]
    return names + [f"functions.{f.lower()}.default" for f in functions]


def plan(release: dict) -> list[tuple[str, str, dict[str, object]]]:
    """(namespace, name, {key: value or RANDOM}) for every Secret the release needs."""
    tenant, values = release["tenant"], release["values"]
    available = lab_settings(release["lab"])
    wanted = values["secretSettings"]["keys"]
    missing = [k for k in wanted if k not in available]
    if missing:
        raise SystemExit(f"FAIL no laptop value for secret setting(s) {', '.join(missing)}")
    functions = values["functions"]["http"] + values["functions"]["worker"]
    return [
        (tenant, values["secretSettings"]["secretName"], {k: available[k] for k in wanted}),
        (tenant, values["functionKeys"]["secretName"], dict.fromkeys(function_key_names(functions), RANDOM)),
    ]


def kubectl(context: str | None, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    base = ["kubectl", *(["--context", context] if context else [])]
    return subprocess.run([*base, *args], capture_output=True, text=True, check=False, input=stdin)


def existing(context: str | None, namespace: str, name: str) -> dict[str, str]:
    found = kubectl(context, "-n", namespace, "get", "secret", name, "-o", "json")
    if found.returncode != 0:
        return {}
    data = json.loads(found.stdout).get("data") or {}
    return {k: base64.b64decode(v).decode() for k, v in data.items()}


def resolve(wanted: dict[str, object], have: dict[str, str], rotate: bool) -> dict[str, str]:
    out = {}
    for key, value in wanted.items():
        if value is RANDOM:
            out[key] = have[key] if key in have and not rotate else secrets.token_urlsafe(32)
        else:
            out[key] = value
    return out


def manifest(namespace: str, name: str, data: dict[str, str], tenant: str) -> str:
    secret = {
        "apiVersion": "v1",
        "kind": "Secret",
        "type": "Opaque",
        "metadata": {"name": name, "namespace": namespace, "labels": {**MANAGED, "platform.lab/tenant": tenant}},
        "data": {k: base64.b64encode(v.encode()).decode() for k, v in sorted(data.items())},
    }
    return json.dumps(secret)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tenant")
    parser.add_argument("--context", help="kubectl context (default: the current one)")
    parser.add_argument("--rotate", action="store_true", help="new random values (restart the tenant's pods after)")
    args = parser.parse_args()
    profile = dict(
        line.split("=", 1)
        for line in (ROOT / "versions.env").read_text().splitlines()
        if "=" in line and line[0] != "#"
    )["MINIKUBE_PROFILE"]
    context = args.context or kubectl(None, "config", "current-context").stdout.strip()
    if context != profile:
        print(f"FAIL context {context!r} is not the laptop cluster {profile!r}: these values only fit the emulators")
        return 2
    release = yaml.safe_load((ROOT / "platform" / "releases" / f"{args.tenant}.yaml").read_text(encoding="utf-8"))
    secrets_planned = plan(release)
    written = {}
    for namespace, name, wanted in secrets_planned:
        have = existing(context, namespace, name)
        data = resolve(wanted, have, args.rotate)
        written[name] = data
        applied = kubectl(context, "apply", "-f", "-", stdin=manifest(namespace, name, data, args.tenant))
        if applied.returncode != 0:
            print(f"FAIL secret {namespace}/{name}: {applied.stderr.strip()[-200:]}")
            return 1
        kept = sum(1 for k in data if k in have and have[k] == data[k])
        print(f"OK   secret {namespace}/{name}: {len(data)} keys ({kept} kept, {len(data) - kept} new)")
    keys_secret = release["values"]["functionKeys"]["secretName"]
    keda = {"apiKey": written[keys_secret]["host.function.keda"]}
    name = f"{args.tenant}-queue-depth"
    applied = kubectl(context, "apply", "-f", "-", stdin=manifest("keda", name, keda, args.tenant))
    if applied.returncode != 0:
        print(f"FAIL secret keda/{name}: {applied.stderr.strip()[-200:]}")
        return 1
    print(f"OK   secret keda/{name}: KEDA's host key for {args.tenant}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
