# secure-ai-platform

Capstone of the Cloud AI Architect portfolio: one Kubernetes platform that hosts three earlier projects as tenants
([ticket-triage-agent](https://github.com/salmanamn/ticket-triage-agent),
[arabic-voice-assistant](https://github.com/salmanamn/arabic-voice-assistant),
[meeting-summarizer](https://github.com/salmanamn/meeting-summarizer)) on minikube and then on AKS, with one
admission policy, tenant isolation, workload identity, Key Vault CSI and private endpoints.

**Status:** M2 — tenant isolation on a laptop cluster (M1: the admission policy). Decisions: [docs/decisions.md](docs/decisions.md)
([index](docs/decisions-index.md)).

## Admission policy (M1, M2)

| Constraint | What it refuses |
|---|---|
| `platform-tenant-namespace` | a namespace that is not the platform's without owner labels or Pod Security `restricted` (enforce, warn, audit) |
| `platform-allowed-images` | an image outside `ghcr.io/salmanamn/` and `mcr.microsoft.com/`, or without a digest or a tag other than `latest` |
| `platform-container-resources` | a container without CPU and memory requests and a memory limit |
| `platform-no-sa-token` | a pod spec that does not set `automountServiceAccountToken: false` |
| `platform-tenant-network-policy` | a tenant NetworkPolicy that admits other namespaces or addresses, reaches a namespace other than `kube-system` or a range not listed for that tenant, or has a rule without peers |
| `platform-tenant-role-binding` | a tenant RoleBinding to anything but the platform's tenant roles, or to users, other tenants' groups or other namespaces' service accounts |

Rules judge Deployments, StatefulSets, DaemonSets, ReplicaSets, Jobs and CronJobs at apply time, not only pods.
Every case in `policy/gatekeeper/rules/*/cases/` is checked by regopy (unit tests), gator (CI) and a live cluster
(`scripts/live_cases.py`); `scripts/policy_must_fail.py` weakens the policy and the tenancy objects 27 ways and
requires each to be caught.

## Tenancy (M2)

`platform/tenants.yaml` → `scripts/build_platform.py` → `platform/generated/<tenant>.yaml` for `triage`, `voice`,
`meetings`: the namespace, a quota (no LoadBalancer or NodePort Services), per-container limits without defaults,
role bindings for `tenant:<tenant>:admins` and `:readers`, and the baseline network policies (deny all, DNS only).
The roles (`platform/cluster/roles.yaml`) give tenant admins their workloads but no Secrets, no network policies and
no RBAC. `platform/checks/rbac-matrix.yaml` is checked offline (unit tests) and live; `scripts/check_tenancy.py`
also checks quotas and limits, the network baseline with probe pods, and `kubectl debug`.

## Run it

```bash
uv sync && uv run pytest
./scripts/install-gator.sh && gator verify policy/gatekeeper/suite.yaml
./scripts/cluster.sh up && ./scripts/platform.sh gatekeeper && ./scripts/platform.sh policy && ./scripts/platform.sh tenants
uv run python scripts/live_cases.py && uv run python scripts/check_tenancy.py
```

## Licence

MIT (see `LICENSE`).