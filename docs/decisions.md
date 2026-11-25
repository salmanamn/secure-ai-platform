# Decisions

## D1 — Scope: one platform, three tenants
- The capstone: one Kubernetes platform that hosts the workloads of Projects 3, 4 and 5 (ticket triage, the Arabic voice assistant, the meeting summarizer) as tenants, first on minikube, then on AKS. The platform owns the cluster, admission policy, tenancy (namespaces, RBAC, quotas, network policy), identity, secrets and private networking; each tenant owns its code and its chart.
- What it adds over the three projects: the private networking they left out (Project 3 D15, Project 5: private endpoints and VNet integration → Project 7), one admission policy for every tenant, and workload identity plus Key Vault CSI as the only way a tenant reaches Azure.
- Same rule as before: what runs on the laptop runs on Azure; only configuration differs.

## D2 — This repo holds the platform; tenant code stays in its repos
- `secure-ai-platform`: cluster IaC (M5), the policy library (`policy/`), platform manifests (`platform/`), tenant onboarding (namespaces, RBAC, quotas, identities), the deploy glue, and the checks that the platform behaves the same on minikube and AKS.
- Tenant images are built and published by their own repos (GHCR today; the platform's ACR on AKS, M5); this repo pins which versions it runs.

## D3 — Tenancy: one namespace per tenant, labelled with its owner
- Namespaces `triage`, `voice`, `meetings` (`platform/namespaces/tenants.yaml`), each labelled `platform.lab/tenant`, `platform.lab/owner` and `platform.lab/source` (the repo). `platform.lab` is a label prefix of this lab, not a domain anyone owns.
- Platform namespaces (Kubernetes', the CNI's, Gatekeeper's) are listed in the namespace rule's parameters; every other namespace is a tenant's and must say so (D7).

## D4 — Rules judge the workload, not only the pod
- `policy/gatekeeper/lib/workload.rego` finds the pod spec in a Pod, in the pod template of a Deployment, StatefulSet, DaemonSet, ReplicaSet or Job, and in a CronJob's job template. A bad Deployment is refused when it is applied, with the reason on the operator's screen, instead of being accepted and then failing to create pods (the ReplicaSet controller's error is only in events).
- `containers` = containers and init containers (both can set resources); `all_containers` adds ephemeral containers (`kubectl debug`), which run images too.

## D5 — Gatekeeper, rules as sources, three checks of the same cases
- Engine on the laptop: OPA Gatekeeper **3.23.1** (latest stable on 2026-11-25; 3.24.0 is in beta), Helm chart 3.23.1 (`platform/gatekeeper/values.yaml`).
- One directory per rule (`policy/gatekeeper/rules/<rule>/`: `rule.yaml`, `rule.rego`, `constraint.yaml`, `cases/`). `scripts/build_policy.py` generates the ConstraintTemplates (`policy/gatekeeper/templates/`, Rego and libs embedded) and gator's test suite (`policy/gatekeeper/suite.yaml`); both are committed, never edited by hand, and a unit test fails when they are stale.
- Rego is written in the syntax both Rego versions accept (`import future.keywords.*`, `contains` / `if`), so the same template loads in Gatekeeper's default (v0) mode and in any engine that only speaks v1.
- Every case is checked three ways: **regopy** evaluates the generated templates' Rego in the unit tests (no cluster, no gator); **gator verify** runs the suite in CI; **`scripts/live_cases.py`** sends each case to a live cluster with `kubectl apply --dry-run=server` (all admission runs, nothing is stored) and requires a disallowed case to be denied by its own constraint alone. `scripts/policy_must_fail.py` weakens the policy 14 ways and requires the tests (and gator, in CI) to catch each.
- **On AKS (proposed, decided in M5):** the Azure Policy add-on, which runs its own managed Gatekeeper, with these templates as custom policy definitions (`templateInfo.sourceType: Base64Encoded`, generated from the same files). Open Gatekeeper and the add-on are not run together; the add-on's Gatekeeper version and its support for `libs` are checked then.

## D6 — Images: from the platform's registries, with a version
- Every image starts with an allowed prefix (now `ghcr.io/salmanamn/` and `mcr.microsoft.com/`; the platform's ACR joins in M5) and names a version: a digest, or a tag other than `latest`. The tag is read from the part after the last `/`, so a registry port is never taken for a tag.
- Prefixes end with `/` (schema `pattern` and a unit test), so `ghcr.io/salmanamn/` does not admit `ghcr.io/salmanamnx/`.
- Not proven yet: ephemeral containers. They are in the rule, but there is no case: the API server refuses them on create, and `kubectl debug` goes through the `pods/ephemeralcontainers` subresource. M2 tries `kubectl debug` on the cluster.

## D7 — Pod security is Pod Security Admission at "restricted"; Gatekeeper makes it mandatory
- Pod-level security (privileged, host namespaces and paths, capabilities, non-root, seccomp, privilege escalation) is Kubernetes' built-in Pod Security Admission at `restricted`, which minikube and AKS both run, rather than a second copy of the same checks in Rego.
- What Gatekeeper adds: no tenant namespace can opt out. `platform-tenant-namespace` refuses a namespace without the owner labels or without `restricted` for all three modes (`enforce` blocks pods, `warn` shows the reason when a Deployment is applied, `audit` records it).

## D8 — Containers request CPU and memory and limit memory; no CPU limit
- `platform-container-resources`: every container and init container sets `requests.cpu`, `requests.memory` and `limits.memory`. No CPU limit is required: throttling hurts latency (Project 4's turn budget), and the namespace quota (M2) caps a tenant's total.

## D9 — Pods mount no Kubernetes API token
- `platform-no-sa-token`: the pod spec sets `automountServiceAccountToken: false`. Tenant workloads never call the Kubernetes API; on AKS they reach Azure through workload identity, whose token is a separate projected volume (Project 4 M8 ran without a Kubernetes token). The pod's field is required, not the service account's, because the pod's overrides it.
- Consequence for M3: the Functions host must not keep its keys in Kubernetes secrets (`AzureWebJobsSecretStorageType=kubernetes` needs the API); it uses files.

## D10 — Admission fails closed for tenants, never for the cluster itself
- The validating webhook's failure policy is `Fail`: when Gatekeeper is down, tenant workloads cannot be created or changed. With one replica on the laptop that is a real outage; it is the intended trade (AKS sizing in M5).
- **The webhook only sees what the constraints judge** (`validatingWebhookCustomRules`): Pods (and `pods/ephemeralcontainers`, D6), Deployments, StatefulSets, DaemonSets, ReplicaSets, Jobs, CronJobs and Namespaces, CREATE and UPDATE. The chart's default sends every resource, cluster-scoped ones included, so with `Fail` a stopped Gatekeeper blocked everything outside the exempt namespaces — on 2026-11-26 it blocked Helm's own `ClusterRole` for the Gatekeeper upgrade (a deadlock: the fix could not be installed while the webhook waited for it), and it would block node leases in `kube-node-lease`. A unit test keeps the rules equal to the constraints' kinds and refuses wildcards.
- `kube-system` carries `admission.gatekeeper.sh/ignore` (chart: `controllerManager.exemptNamespaces` plus `postInstall.labelNamespace.extraNamespaces`), so the webhook never sees the cluster's own pods and an outage cannot stop them; `gatekeeper-system` is exempt by the chart. The constraints exclude both again, which keeps them out of the audit too.

## D11 — The laptop cluster: minikube, Kubernetes 1.36, Calico
- Profile `aiplat` (`scripts/cluster.sh`), Kubernetes **v1.36.4**: the minor version Project 4 ran on AKS (its D53: 1.36 until azurerm can set the node pool's LocalDNS profile; 1.37 became GA and LTS on AKS in October 2026, checked again in M5). Calico for NetworkPolicy (M2), metrics-server; 4 CPUs, 6 GB.
- kubectl 1.37 talks to 1.36 within the supported skew.

## D12 — Tool versions in one file; gator pinned by checksum
- `versions.env` holds the Gatekeeper version, gator's SHA-256 (of `gator-v3.23.1-linux-amd64.tar.gz` from the GitHub release, taken 2026-11-25), the Kubernetes version and the minikube profile. `scripts/install-gator.sh` checks the archive before unpacking it, on the laptop and in CI.

## D13 — A decisions index from day one
- `docs/decisions-index.md` is generated from the headings of this file by `scripts/decisions_index.py` (Project 5's script, its D11), and `tests/unit/test_decisions.py` fails when the index is stale or a number is missing or repeated. A decision's status lives in the decision (`- **Status:** …`); updates are new decisions whose heading says `(updates Dx)`.

## D14 — CI and branch protection from the first milestone
- `.github/workflows/ci.yml`: `lint` (ruff, generated files and decisions index current, shellcheck, actionlint), `unit` (pytest: every case through regopy, the decisions drift test), `policy` (gator verify, then `policy_must_fail.py --require-gator`). `permissions: contents: read`, no secrets.
- `main` protected by `scripts/protect-main.sh` (Project 5's) with those three checks once they are green.