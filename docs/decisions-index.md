# Decisions index

Generated from the headings of [decisions.md](decisions.md) by `scripts/decisions_index.py`; don't edit it by
hand. `tests/unit/test_decisions.py` fails when this file and the headings disagree, or when a number is
missing or used twice.

28 decisions (D1–D28): 3 updated by a later one, 2 with a status of
their own (open questions, workarounds); the rest accepted as written.

| # | Decision | Status |
|---|---|---|
| [D1](decisions.md#d1--scope-one-platform-three-tenants) | Scope: one platform, three tenants | accepted |
| [D2](decisions.md#d2--this-repo-holds-the-platform-tenant-code-stays-in-its-repos) | This repo holds the platform; tenant code stays in its repos | accepted |
| [D3](decisions.md#d3--tenancy-one-namespace-per-tenant-labelled-with-its-owner) | Tenancy: one namespace per tenant, labelled with its owner | accepted |
| [D4](decisions.md#d4--rules-judge-the-workload-not-only-the-pod) | Rules judge the workload, not only the pod | accepted |
| [D5](decisions.md#d5--gatekeeper-rules-as-sources-three-checks-of-the-same-cases) | Gatekeeper, rules as sources, three checks of the same cases | accepted; updated by D21 |
| [D6](decisions.md#d6--images-from-the-platforms-registries-with-a-version) | Images: from the platform's registries, with a version | proven on the cluster (M2, `docs/evidence/m2-tenancy.txt`): `kubectl debug --profile=restricted` with a docker.io image is refused by `platform-allowed-images`, with an MCR image admitted |
| [D7](decisions.md#d7--pod-security-is-pod-security-admission-at-restricted-gatekeeper-makes-it-mandatory) | Pod security is Pod Security Admission at "restricted"; Gatekeeper makes it mandatory | accepted |
| [D8](decisions.md#d8--containers-request-cpu-and-memory-and-limit-memory-no-cpu-limit) | Containers request CPU and memory and limit memory; no CPU limit | accepted |
| [D9](decisions.md#d9--pods-mount-no-kubernetes-api-token) | Pods mount no Kubernetes API token | accepted |
| [D10](decisions.md#d10--admission-fails-closed-for-tenants-never-for-the-cluster-itself) | Admission fails closed for tenants, never for the cluster itself | accepted |
| [D11](decisions.md#d11--the-laptop-cluster-minikube-kubernetes-136-calico) | The laptop cluster: minikube, Kubernetes 1.36, Calico | accepted |
| [D12](decisions.md#d12--tool-versions-in-one-file-gator-pinned-by-checksum) | Tool versions in one file; gator pinned by checksum | accepted |
| [D13](decisions.md#d13--a-decisions-index-from-day-one) | A decisions index from day one | accepted |
| [D14](decisions.md#d14--ci-and-branch-protection-from-the-first-milestone) | CI and branch protection from the first milestone | accepted |
| [D15](decisions.md#d15--tenancy-objects-are-generated-from-one-spec) | Tenancy objects are generated from one spec | accepted |
| [D16](decisions.md#d16--the-platforms-own-tenant-roles-not-the-built-in-ones) | The platform's own tenant roles, not the built-in ones | accepted |
| [D17](decisions.md#d17--quotas-and-limits-caps-no-defaults) | Quotas and limits: caps, no defaults | proven on the cluster (M2, `docs/evidence/m2-tenancy.txt`): Kubernetes 1.36 checks both the ResourceQuota and the LimitRange on `kubectl apply --dry-run=server`, so the five admission cases refuse or admit without creating anything |
| [D18](decisions.md#d18--network-every-tenant-starts-closed-tenant-policies-stay-inside-the-tenant) | Network: every tenant starts closed; tenant policies stay inside the tenant | accepted; updated by D23, D24 |
| [D19](decisions.md#d19--tenant-role-bindings-grant-tenant-roles-to-that-tenant-only) | Tenant role bindings grant tenant roles to that tenant only | accepted |
| [D20](decisions.md#d20--the-live-tenancy-check) | The live tenancy check | accepted; updated by D21 |
| [D21](decisions.md#d21--evidence-only-from-a-cluster-that-answered-before-and-after-the-run-updates-d5-d20) | Evidence only from a cluster that answered before and after the run | accepted; updates D5, D20 |
| [D22](decisions.md#d22--keda-is-a-platform-component-and-reads-no-tenants-secrets) | KEDA is a platform component, and reads no tenant's Secrets | accepted |
| [D23](decisions.md#d23--tenant-data-services-on-the-laptop-a-range-on-minikubes-network-updates-d18) | Tenant data services on the laptop: a range on minikube's network | accepted; updates D18 |
| [D24](decisions.md#d24--tenant-ingress-from-platform-namespaces-named-exactly-updates-d18) | Tenant ingress from platform namespaces, named exactly | accepted; updates D18 |
| [D25](decisions.md#d25--tenant-releases-the-tenants-own-chart-at-a-pinned-commit-rendered-and-committed) | Tenant releases: the tenant's own chart at a pinned commit, rendered and committed | accepted |
| [D26](decisions.md#d26--tenant-secrets-are-the-operators-on-the-laptop-emulator-keys-and-random-host-keys) | Tenant Secrets are the operator's: on the laptop, emulator keys and random host keys | accepted |
| [D27](decisions.md#d27--the-first-tenant-on-the-laptop-ticket-triage) | The first tenant on the laptop: ticket triage | accepted |
| [D28](decisions.md#d28--the-tenant-check) | The tenant check | accepted |
