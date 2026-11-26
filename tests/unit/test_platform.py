"""The tenancy objects (D15-D20): generated from platform/tenants.yaml, obeying the platform's own policy, and
granting exactly what platform/checks/rbac-matrix.yaml says, checked here without a cluster."""

import build_platform
import check_tenancy
import pytest
import yaml
from test_policy import RULES, violations

ROOT = build_platform.ROOT
SPEC = build_platform.load_spec()
GENERATED = {path.stem: list(yaml.safe_load_all(text)) for path, text in build_platform.outputs(SPEC).items()}
CLUSTER = list(yaml.safe_load_all((ROOT / "platform/cluster/roles.yaml").read_text(encoding="utf-8")))
ALL_OBJECTS = [obj for documents in GENERATED.values() for obj in documents] + CLUSTER


def objects(kind: str, documents: list[dict] = ALL_OBJECTS) -> list[dict]:
    return [o for o in documents if o["kind"] == kind]


def test_generated_files_are_up_to_date():
    for path, text in build_platform.outputs().items():
        assert path.read_text(encoding="utf-8") == text, f"{path.name} is stale: run scripts/build_platform.py"


def test_one_file_per_tenant_and_nothing_else():
    assert sorted(GENERATED) == sorted(t["name"] for t in SPEC["tenants"]) == ["meetings", "triage", "voice"]
    assert sorted(p.stem for p in (ROOT / "platform/generated").glob("*.yaml")) == sorted(GENERATED)


@pytest.mark.parametrize(
    "obj", ALL_OBJECTS, ids=lambda o: f"{o['kind']}/{o['metadata'].get('namespace', '-')}/{o['metadata']['name']}"
)
def test_the_platforms_objects_obey_the_platforms_policy(obj):
    for rule in RULES:
        assert violations(rule, obj) == [], rule.directory.name


@pytest.mark.parametrize("tenant", sorted(GENERATED))
def test_every_tenant_starts_closed(tenant):
    documents = GENERATED[tenant]
    assert documents[0]["kind"] == "Namespace"  # applied first
    policies = {p["metadata"]["name"]: p["spec"] for p in objects("NetworkPolicy", documents)}
    assert policies["platform-default-deny"] == {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]}
    dns = policies["platform-allow-dns"]
    assert dns["policyTypes"] == ["Egress"] and "ingress" not in dns
    assert [p["port"] for p in dns["egress"][0]["ports"]] == [53, 53]
    assert len(policies) == 2  # nothing else is open by default


@pytest.mark.parametrize("tenant", sorted(GENERATED))
def test_quota_and_limits(tenant):
    (quota,) = objects("ResourceQuota", GENERATED[tenant])
    hard = quota["spec"]["hard"]
    assert hard["services.loadbalancers"] == "0" and hard["services.nodeports"] == "0"
    assert {"requests.cpu", "requests.memory", "limits.memory", "pods"} <= set(hard)
    (limits,) = objects("LimitRange", GENERATED[tenant])
    (entry,) = limits["spec"]["limits"]
    # No default or defaultRequest: a default would fill in resources and hide a missing request from
    # platform-container-resources (D8, D17).
    assert set(entry) == {"type", "max"} and entry["type"] == "Container"


def test_every_platform_object_is_labelled_managed():
    for obj in ALL_OBJECTS:
        assert obj["metadata"]["labels"]["platform.lab/managed"] == "true", obj["metadata"]["name"]


def test_egress_ranges_are_only_for_known_tenants():
    (rule,) = [r for r in RULES if r.kind == "K8sPlatformTenantNetworkPolicy"]
    assert set(rule.constraint["spec"]["parameters"]["egressCIDRs"]) <= set(GENERATED)


# --- RBAC, offline -------------------------------------------------------------------------------------------------


def subject_matches(binding_subject: dict, user: str, groups: list[str]) -> bool:
    kind = binding_subject["kind"]
    if kind == "Group":
        return binding_subject["name"] in groups
    if kind == "User":
        return binding_subject["name"] == user
    return user == f"system:serviceaccount:{binding_subject['namespace']}:{binding_subject['name']}"


def allowed(user: str, groups: list[str], verb: str, resource: str, namespace: str | None) -> bool:
    """Kubernetes RBAC for the objects in this repo: bindings grant ClusterRoles; cluster-admin grants everything."""
    group, name = check_tenancy.parse_resource(resource)
    roles = {r["metadata"]["name"]: r for r in objects("ClusterRole")}
    bindings = [b for b in objects("ClusterRoleBinding")]
    if namespace:
        bindings += [b for b in objects("RoleBinding") if b["metadata"]["namespace"] == namespace]
    for binding in bindings:
        if not any(subject_matches(s, user, groups) for s in binding["subjects"]):
            continue
        if binding["roleRef"]["name"] == "cluster-admin":
            return True
        for rule in roles[binding["roleRef"]["name"]]["rules"]:
            if (
                group in rule["apiGroups"]
                and name in rule["resources"]
                and (verb in rule["verbs"] or "*" in rule["verbs"])
            ):
                return True
    return False


SUBJECTS, MATRIX = check_tenancy.load_matrix()


@pytest.mark.parametrize("row", MATRIX, ids=lambda r: f"{r[0]}-{r[1]}-{r[2]}-{r[3]}")
def test_rbac_matrix_offline(row):
    name, verb, resource, namespace, expected = row
    subject = SUBJECTS[name]
    assert allowed(subject["user"], subject["groups"], verb, resource, namespace) is expected


def test_no_role_uses_wildcards_or_grants_secrets():
    for role in objects("ClusterRole"):
        for rule in role["rules"]:
            assert "*" not in rule["apiGroups"] + rule["resources"] + rule["verbs"], role["metadata"]["name"]
            assert "secrets" not in rule["resources"], role["metadata"]["name"]


@pytest.mark.parametrize(
    ("text", "parsed"),
    [
        ("pods", ("", "pods")),
        ("deployments.apps", ("apps", "deployments")),
        ("networkpolicies.networking.k8s.io", ("networking.k8s.io", "networkpolicies")),
        ("pods/exec", ("", "pods/exec")),
    ],
)
def test_parse_resource(text, parsed):
    assert check_tenancy.parse_resource(text) == parsed


# --- the live checks' own files obey the policy ------------------------------------------------------------------


def check_files() -> list[dict]:
    files = [
        *sorted((ROOT / "platform/checks/admission").glob("*.yaml")),
        ROOT / "platform/checks/netpol-probe-allow.yaml",
    ]
    return [obj for p in files for obj in yaml.safe_load_all(p.read_text(encoding="utf-8"))]


def test_the_allow_rules_cover_both_ends():
    """Round 2 expects triage/client -> triage/server open: that needs the server's ingress and the client's egress."""
    allow = list(yaml.safe_load_all((ROOT / "platform/checks/netpol-probe-allow.yaml").read_text(encoding="utf-8")))
    sides = {
        (p["spec"]["podSelector"]["matchLabels"]["platform.lab/probe"], tuple(p["spec"]["policyTypes"])) for p in allow
    }
    assert sides == {("server", ("Ingress",)), ("client", ("Egress",))}


def test_check_objects_and_probes_pass_gatekeeper():
    """Admission denials must come from the quota or limits, never from Gatekeeper; probes must be admitted."""
    probes = [
        yaml.safe_load(check_tenancy.probe_manifest(*k.split("/"), role)) for k, role in check_tenancy.PROBES.items()
    ]
    for obj in check_files() + probes:
        for rule in RULES:
            assert violations(rule, obj) == [], f"{obj['metadata']['name']}: {rule.directory.name}"


@pytest.mark.parametrize(
    ("name", "returncode", "output", "verdict"),
    [
        ("allowed-within-limits", 0, "pod/x created (server dry run)", (True, "admitted")),
        ("allowed-within-limits", 1, "exceeded quota", (False, "denied")),
        (
            "denied-nodeport",
            1,
            "exceeded quota: platform-quota, requested: services.nodeports=1",
            (True, "denied as expected"),
        ),
        ("denied-nodeport", 0, "service/x created (server dry run)", (False, "admitted")),
        ("denied-nodeport", 1, 'admission webhook "validation.gatekeeper.sh" denied', (False, "denied by Gatekeeper")),
        ("denied-nodeport", 1, 'namespaces "triage" not found', (False, "denied for another reason")),
    ],
)
def test_admission_verdict(name, returncode, output, verdict):
    expect = "exceeded quota: platform-quota.*services.nodeports" if name == "denied-nodeport" else None
    assert check_tenancy.admission_verdict(name, expect, returncode, output) == verdict


def test_probes_and_checks_call_python3():
    """The probe image (Azure Linux 3.0) has python3 and no `python`: a probe running `python` never starts."""
    probe = yaml.safe_load(check_tenancy.probe_manifest("triage", "probe-x", "client"))
    assert probe["spec"]["containers"][0]["command"][0] == "python3"
    pods = [o for o in check_files() if o["kind"] == "Pod"]
    assert pods and all(c["command"][0] == "python3" for p in pods for c in p["spec"]["containers"])


def test_a_section_that_stops_still_writes_its_failure(monkeypatch, tmp_path):
    def stop(context):
        raise SystemExit("probe triage/client not ready: timed out")

    monkeypatch.setattr(check_tenancy, "SECTIONS", {"network": stop})
    monkeypatch.setattr(
        check_tenancy, "kubectl", lambda *a, **k: check_tenancy.subprocess.CompletedProcess(a, 0, "", "")
    )
    monkeypatch.setattr(check_tenancy, "cleanup", lambda context: None)
    evidence = tmp_path / "e.txt"
    monkeypatch.setattr("sys.argv", ["check_tenancy.py", "--evidence", str(evidence)])
    assert check_tenancy.main() == 1
    text = evidence.read_text()
    assert "FAIL network section: expected completed, seen probe triage/client not ready" in text
    assert text.rstrip().endswith("FAIL 1 of 1")
