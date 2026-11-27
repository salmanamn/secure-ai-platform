# secure-ai-platform

Capstone of the Cloud AI Architect portfolio: one Kubernetes platform that hosts three earlier projects as tenants
([ticket-triage-agent](https://github.com/salmanamn/ticket-triage-agent),
[arabic-voice-assistant](https://github.com/salmanamn/arabic-voice-assistant),
[meeting-summarizer](https://github.com/salmanamn/meeting-summarizer)) on minikube and then on AKS, with one
admission policy, tenant isolation, workload identity, Key Vault CSI and private endpoints.

**Status:** M3 — ticket triage as the first tenant, on a laptop cluster (M1: the admission policy; M2: tenant isolation). Decisions: [docs/decisions.md](docs/decisions.md)
([index](docs/decisions-index.md)).

## Admission policy (M1–M3)

| Constraint | What it refuses |
|---|---|
| `platform-tenant-namespace` | a namespace that is not the platform's without owner labels or Pod Security `restricted` (enforce, warn, audit) |
| `platform-allowed-images` | an image outside `ghcr.io/salmanamn/` and `mcr.microsoft.com/`, or without a digest or a tag other than `latest` |
| `platform-container-resources` | a container without CPU and memory requests and a memory limit |
| `platform-no-sa-token` | a pod spec that does not set `automountServiceAccountToken: false` |
| `platform-tenant-network-policy` | a tenant NetworkPolicy that admits other namespaces (KEDA's excepted) or addresses, reaches a namespace other than `kube-system` or a range not listed for that tenant, or has a rule without peers |
| `platform-tenant-role-binding` | a tenant RoleBinding to anything but the platform's tenant roles, or to users, other tenants' groups or other namespaces' service accounts |

Rules judge Deployments, StatefulSets, DaemonSets, ReplicaSets, Jobs and CronJobs at apply time, not only pods.
Every case in `policy/gatekeeper/rules/*/cases/` is checked by regopy (unit tests), gator (CI) and a live cluster
(`scripts/live_cases.py`); `scripts/policy_must_fail.py` weakens the policy, the tenancy objects and the tenant
releases 37 ways and requires each to be caught.

## Tenancy (M2)

`platform/tenants.yaml` → `scripts/build_platform.py` → `platform/generated/<tenant>.yaml` for `triage`, `voice`,
`meetings`: the namespace, a quota (no LoadBalancer or NodePort Services), per-container limits without defaults,
role bindings for `tenant:<tenant>:admins` and `:readers`, and the baseline network policies (deny all, DNS only).
The roles (`platform/cluster/roles.yaml`) give tenant admins their workloads but no Secrets, no network policies and
no RBAC. `platform/checks/rbac-matrix.yaml` is checked offline (unit tests) and live; `scripts/check_tenancy.py`
also checks quotas and limits, the network baseline with probe pods, and `kubectl debug`.

## Tenants (M3)

A tenant brings its own chart and image; the platform pins both and renders them:
`platform/releases/<tenant>.yaml` (chart at a commit, image by digest, the platform's values) →
`scripts/render_tenants.py` → `platform/rendered/<tenant>.yaml`, which the unit tests check against every rule
(no exemptions) and `./scripts/platform.sh tenant <name>` applies with the Secrets the operator creates. KEDA is a
platform component and reads Secrets only in its own namespace.

The first tenant is [ticket-triage-agent](https://github.com/salmanamn/ticket-triage-agent): its Functions app as
two deployments of one image, the Service Bus trigger scaled by KEDA from zero, against Project 3's emulators on
minikube's network. `scripts/check_triage.py` sends three tickets through it and checks the scaling, the triage and
the emails ([evidence](docs/evidence/m3-triage.txt)).

## Run it

```bash
uv sync && uv run pytest
./scripts/install-gator.sh && gator verify policy/gatekeeper/suite.yaml
./scripts/cluster.sh up && ./scripts/platform.sh namespaces && ./scripts/platform.sh gatekeeper && ./scripts/platform.sh policy
./scripts/platform.sh tenants && ./scripts/platform.sh keda && ./scripts/platform.sh tenant triage
uv run python scripts/live_cases.py && uv run python scripts/check_tenancy.py && uv run python scripts/check_triage.py
```

## Licence

MIT (see `LICENSE`).