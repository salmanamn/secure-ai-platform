# Decisions index

Generated from the headings of [decisions.md](decisions.md) by `scripts/decisions_index.py`; don't edit it by
hand. `tests/unit/test_decisions.py` fails when this file and the headings disagree, or when a number is
missing or used twice.

14 decisions (D1–D14): 0 updated by a later one, 0 with a status of
their own (open questions, workarounds); the rest accepted as written.

| # | Decision | Status |
|---|---|---|
| [D1](decisions.md#d1--scope-one-platform-three-tenants) | Scope: one platform, three tenants | accepted |
| [D2](decisions.md#d2--this-repo-holds-the-platform-tenant-code-stays-in-its-repos) | This repo holds the platform; tenant code stays in its repos | accepted |
| [D3](decisions.md#d3--tenancy-one-namespace-per-tenant-labelled-with-its-owner) | Tenancy: one namespace per tenant, labelled with its owner | accepted |
| [D4](decisions.md#d4--rules-judge-the-workload-not-only-the-pod) | Rules judge the workload, not only the pod | accepted |
| [D5](decisions.md#d5--gatekeeper-rules-as-sources-three-checks-of-the-same-cases) | Gatekeeper, rules as sources, three checks of the same cases | accepted |
| [D6](decisions.md#d6--images-from-the-platforms-registries-with-a-version) | Images: from the platform's registries, with a version | accepted |
| [D7](decisions.md#d7--pod-security-is-pod-security-admission-at-restricted-gatekeeper-makes-it-mandatory) | Pod security is Pod Security Admission at "restricted"; Gatekeeper makes it mandatory | accepted |
| [D8](decisions.md#d8--containers-request-cpu-and-memory-and-limit-memory-no-cpu-limit) | Containers request CPU and memory and limit memory; no CPU limit | accepted |
| [D9](decisions.md#d9--pods-mount-no-kubernetes-api-token) | Pods mount no Kubernetes API token | accepted |
| [D10](decisions.md#d10--admission-fails-closed-for-tenants-never-for-the-cluster-itself) | Admission fails closed for tenants, never for the cluster itself | accepted |
| [D11](decisions.md#d11--the-laptop-cluster-minikube-kubernetes-136-calico) | The laptop cluster: minikube, Kubernetes 1.36, Calico | accepted |
| [D12](decisions.md#d12--tool-versions-in-one-file-gator-pinned-by-checksum) | Tool versions in one file; gator pinned by checksum | accepted |
| [D13](decisions.md#d13--a-decisions-index-from-day-one) | A decisions index from day one | accepted |
| [D14](decisions.md#d14--ci-and-branch-protection-from-the-first-milestone) | CI and branch protection from the first milestone | accepted |
