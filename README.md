# secure-ai-platform

Capstone of the Cloud AI Architect portfolio: one Kubernetes platform that hosts three earlier projects as tenants
([ticket-triage-agent](https://github.com/salmanamn/ticket-triage-agent),
[arabic-voice-assistant](https://github.com/salmanamn/arabic-voice-assistant),
[meeting-summarizer](https://github.com/salmanamn/meeting-summarizer)) on minikube and then on AKS, with one
admission policy, tenant isolation, workload identity, Key Vault CSI and private endpoints.

**Status:** M1 — the admission policy on a laptop cluster. Decisions: [docs/decisions.md](docs/decisions.md)
([index](docs/decisions-index.md)).

## Admission policy (M1)

| Constraint | What it refuses |
|---|---|
| `platform-tenant-namespace` | a namespace that is not the platform's without owner labels or Pod Security `restricted` (enforce, warn, audit) |
| `platform-allowed-images` | an image outside `ghcr.io/salmanamn/` and `mcr.microsoft.com/`, or without a digest or a tag other than `latest` |
| `platform-container-resources` | a container without CPU and memory requests and a memory limit |
| `platform-no-sa-token` | a pod spec that does not set `automountServiceAccountToken: false` |

Rules judge Deployments, StatefulSets, DaemonSets, ReplicaSets, Jobs and CronJobs at apply time, not only pods.
Every case in `policy/gatekeeper/rules/*/cases/` is checked by regopy (unit tests), gator (CI) and a live cluster
(`scripts/live_cases.py`); `scripts/policy_must_fail.py` weakens the policy 14 ways and requires each to be caught.

## Run it

```bash
uv sync && uv run pytest
./scripts/install-gator.sh && gator verify policy/gatekeeper/suite.yaml
./scripts/cluster.sh up && ./scripts/platform.sh gatekeeper && ./scripts/platform.sh policy && ./scripts/platform.sh tenants
uv run python scripts/live_cases.py
```

## Licence

MIT (see `LICENSE`).