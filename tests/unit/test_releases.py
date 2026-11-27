"""Tenant releases (D22-D27): what the platform applies for a tenant, checked on the committed rendered file.

The rendered file is what `platform.sh tenant` applies, so it is what these tests read: every object against every
Gatekeeper rule (no exemption for a tenant's own chart), and the platform's own promises on top: the tenant's
namespace only, no Secrets or exposed Services, the pinned image, secrets only from the operator, the scaler through
KEDA's namespace, the lab addresses inside the tenant's range, and the quota at full scale.
"""

import ipaddress
import re
from pathlib import Path
from urllib.parse import urlparse

import build_platform
import check_triage
import pytest
import render_tenants
import tenant_secrets
import yaml
from test_policy import RULES, violations

ROOT = render_tenants.ROOT
RELEASES = render_tenants.load_releases()
RENDERED = {
    name: [d for d in yaml.safe_load_all((render_tenants.OUT / f"{name}.yaml").read_text(encoding="utf-8")) if d]
    for name in RELEASES
}
OBJECTS = [(name, obj) for name, docs in RENDERED.items() for obj in docs]
ALLOWED_KINDS = {"ConfigMap", "Deployment", "Service", "ScaledObject", "NetworkPolicy"}
SECRET_NAME = re.compile(r"(KEY|SECRET|PASSWORD|TOKEN|CONNECTION|STORAGE)$", re.I)
NETPOL_RULE = next(r for r in RULES if r.kind == "K8sPlatformTenantNetworkPolicy")
SPEC = build_platform.load_spec()


def ids(item):
    name, obj = item
    return f"{name}/{obj['kind']}/{obj['metadata']['name']}"


def pod_specs(docs: list[dict]) -> list[dict]:
    return [d["spec"]["template"]["spec"] for d in docs if d["kind"] == "Deployment"]


def containers(docs: list[dict]) -> list[dict]:
    return [c for spec in pod_specs(docs) for c in spec["containers"] + spec.get("initContainers", [])]


def test_releases_are_pinned_and_rendered_from_what_they_pin():
    assert RELEASES and set(RELEASES) <= {t["name"] for t in SPEC["tenants"]}
    for name, release in RELEASES.items():
        assert render_tenants.problems(name, release) == []
        header = (render_tenants.OUT / f"{name}.yaml").read_text(encoding="utf-8").splitlines()[:4]
        assert (
            header[1] == f"# chart: {release['chart']['repo']} {release['chart']['path']} at {release['chart']['ref']}"
        )
        image = release["values"]["image"]
        assert header[2] == f"# image: {image['repository']}@{image['digest']}"
        assert header[3] == f"# helm: {render_tenants.versions()['HELM_VERSION']}"
    assert sorted(p.stem for p in render_tenants.OUT.glob("*.yaml")) == sorted(RELEASES)


@pytest.mark.parametrize(
    ("ref", "digest", "found"),
    [
        ("main", "sha256:" + "0" * 64, "chart.ref must be a full commit id"),
        ("a" * 40, "latest", "values.image.digest must be sha256"),
    ],
)
def test_a_release_on_a_branch_or_a_tag_is_refused(ref, digest, found):
    release = {"tenant": "x", "chart": {"ref": ref}, "values": {"image": {"digest": digest}}}
    assert any(found in p for p in render_tenants.problems("x", release))


@pytest.mark.parametrize("item", OBJECTS, ids=ids)
def test_rendered_objects_obey_every_platform_rule(item):
    _, obj = item
    for rule in RULES:
        assert violations(rule, obj) == [], rule.directory.name


@pytest.mark.parametrize("item", OBJECTS, ids=ids)
def test_rendered_objects_stay_in_the_tenant_namespace(item):
    name, obj = item
    assert obj["kind"] in ALLOWED_KINDS, (
        f"a tenant release renders no {obj['kind']} (Secrets and RBAC are the platform's)"
    )
    assert obj["metadata"]["namespace"] == name


@pytest.mark.parametrize("name", sorted(RENDERED))
def test_services_are_cluster_internal(name):
    services = [d for d in RENDERED[name] if d["kind"] == "Service"]
    assert services and {s["spec"].get("type", "ClusterIP") for s in services} == {"ClusterIP"}


@pytest.mark.parametrize("name", sorted(RENDERED))
def test_every_container_runs_the_pinned_image(name):
    image = RELEASES[name]["values"]["image"]
    assert {c["image"] for c in containers(RENDERED[name])} == {f"{image['repository']}@{image['digest']}"}


@pytest.mark.parametrize("name", sorted(RENDERED))
def test_no_secret_setting_in_a_configmap(name):
    for config in (d for d in RENDERED[name] if d["kind"] == "ConfigMap"):
        leaked = [k for k in config.get("data", {}) if SECRET_NAME.search(k) and k != "AzureWebJobsSecretStorageType"]
        assert leaked == [], f"{config['metadata']['name']}: {leaked} belong in the operator's Secret (D26)"


@pytest.mark.parametrize("name", sorted(RENDERED))
def test_secrets_used_are_exactly_the_ones_the_operator_creates(name):
    planned = {secret: set(keys) for _, secret, keys in tenant_secrets.plan(RELEASES[name])}
    used: dict[str, set[str]] = {}
    for c in containers(RENDERED[name]):
        for env in c.get("env", []):
            if ref := env.get("valueFrom", {}).get("secretKeyRef"):
                used.setdefault(ref["name"], set()).add(ref["key"])
    for spec in pod_specs(RENDERED[name]):
        for volume in spec.get("volumes", []):
            if "secret" in volume:
                used.setdefault(volume["secret"]["secretName"], set())
    assert set(used) <= set(planned)
    for secret, keys in used.items():
        assert keys <= planned[secret], f"{secret}: {sorted(keys - planned[secret])} are never created"


@pytest.mark.parametrize("name", sorted(RENDERED))
def test_every_loaded_function_has_its_key_file(name):
    loaded = {
        env["value"]
        for c in containers(RENDERED[name])
        for env in c.get("env", [])
        if env["name"].startswith("AzureFunctionsJobHost__functions__")
    }
    keys = next(keys for _, secret, keys in tenant_secrets.plan(RELEASES[name]) if secret.endswith("function-keys"))
    assert loaded and {f"functions.{f.lower()}.default" for f in loaded} <= set(keys)
    assert "host.systemKey.eventgrid_extension" in keys and "host.function.keda" in keys


@pytest.mark.parametrize("name", sorted(RENDERED))
def test_the_scaler_authenticates_through_keda_s_namespace(name):
    auths = {
        a["metadata"]["name"]: a
        for a in yaml.safe_load_all((ROOT / "platform/keda/trigger-authentications.yaml").read_text(encoding="utf-8"))
    }
    for scaled in (d for d in RENDERED[name] if d["kind"] == "ScaledObject"):
        for trigger in scaled["spec"]["triggers"]:
            ref = trigger["authenticationRef"]
            assert ref["kind"] == "ClusterTriggerAuthentication" and ref["name"] in auths
            (target,) = auths[ref["name"]]["spec"]["secretTargetRef"]
            assert target["name"] == f"{name}-queue-depth"  # the Secret tenant_secrets.py writes in keda


@pytest.mark.parametrize("name", sorted(RELEASES))
def test_lab_addresses_are_the_tenant_s_range_and_the_settings_use_them(name):
    release = RELEASES[name]
    allowed = NETPOL_RULE.constraint["spec"]["parameters"]["egressCIDRs"][name]
    egress = [e["cidr"] for e in release["values"]["network"]["egress"]]
    assert set(egress) <= set(allowed)
    ranges = [ipaddress.ip_network(c) for c in egress]
    for address in release["lab"].values():
        assert any(ipaddress.ip_address(address) in r for r in ranges), address
    settings = release["values"]["settings"]
    assert urlparse(settings["COSMOS_ENDPOINT"]).hostname == release["lab"]["cosmos"]
    assert settings["SMTP_HOST"] == release["lab"]["mailpit"]
    secret = tenant_secrets.lab_settings(release["lab"])
    assert f"sb://{release['lab']['servicebus']};" in secret["ServiceBusConnection"]
    assert f"BlobEndpoint=http://{release['lab']['azurite']}:10000/devstoreaccount1;" in secret["AzureWebJobsStorage"]


def quantity(text: str) -> float:
    """Kubernetes quantities used here: 100m, 1, 256Mi, 4Gi -> cores or bytes."""
    units = {"m": 1e-3, "Ki": 2**10, "Mi": 2**20, "Gi": 2**30}
    for unit, factor in units.items():
        if text.endswith(unit):
            return float(text[: -len(unit)]) * factor
    return float(text)


@pytest.mark.parametrize("name", sorted(RENDERED))
def test_the_release_fits_the_quota_at_full_scale_with_a_rolling_update(name):
    """Every deployment at its maximum (KEDA's maxReplicaCount for the scaled one), plus the largest pod once more
    (a rolling update starts one new pod before it stops an old one): within the tenant's ResourceQuota (D27)."""
    docs = RENDERED[name]
    maximum = {
        s["spec"]["scaleTargetRef"]["name"]: s["spec"]["maxReplicaCount"] for s in docs if s["kind"] == "ScaledObject"
    }
    (quota,) = [
        o
        for o in build_platform.tenant_objects(next(t for t in SPEC["tenants"] if t["name"] == name), SPEC["limits"])
        if o["kind"] == "ResourceQuota"
    ]
    hard = quota["spec"]["hard"]
    totals = {"requests.cpu": 0.0, "requests.memory": 0.0, "limits.memory": 0.0, "pods": 0.0}
    largest = dict.fromkeys(totals, 0.0)
    for deployment in (d for d in docs if d["kind"] == "Deployment"):
        replicas = maximum.get(deployment["metadata"]["name"], deployment["spec"].get("replicas", 1))
        pod = {"requests.cpu": 0.0, "requests.memory": 0.0, "limits.memory": 0.0, "pods": 1.0}
        for c in deployment["spec"]["template"]["spec"]["containers"]:
            pod["requests.cpu"] += quantity(str(c["resources"]["requests"]["cpu"]))
            pod["requests.memory"] += quantity(str(c["resources"]["requests"]["memory"]))
            pod["limits.memory"] += quantity(str(c["resources"]["limits"]["memory"]))
        for key in totals:
            totals[key] += replicas * pod[key]
            largest[key] = max(largest[key], pod[key])
    for key, total in totals.items():
        assert total + largest[key] <= quantity(hard[key]), f"{key}: {total + largest[key]} > {hard[key]}"


def test_keda_is_a_platform_namespace_everywhere():
    """D22: keda is exempt from every constraint and from the webhook, and the platform creates it."""
    for rule in RULES:
        match = rule.constraint["spec"].get("match", {})
        params = rule.constraint["spec"].get("parameters", {})
        assert "keda" in match.get("excludedNamespaces", []) + params.get("platformNamespaces", []), rule.directory.name
    values = yaml.safe_load((ROOT / "platform/gatekeeper/values.yaml").read_text(encoding="utf-8"))
    assert "keda" in values["controllerManager"]["exemptNamespaces"]
    assert "keda" in values["postInstall"]["labelNamespace"]["extraNamespaces"]
    namespaces = list(yaml.safe_load_all((ROOT / "platform/cluster/namespaces.yaml").read_text(encoding="utf-8")))
    assert [n["metadata"]["name"] for n in namespaces] == ["keda"]


def test_keda_reads_secrets_only_in_its_own_namespace():
    values = yaml.safe_load((ROOT / "platform/keda/values.yaml").read_text(encoding="utf-8"))
    assert values["permissions"]["operator"]["restrict"]["secret"] is True
    assert values["permissions"]["metricServer"]["restrict"]["secret"] is True
    assert values["rbac"]["enabledCustomScaledRefKinds"] is False  # else `get` on "*" in "*" (D22)


# --- the operator's secrets script ------------------------------------------------------------------------------


def test_secret_values_are_kept_unless_rotated():
    wanted = {"fixed": "value", "made-up": tenant_secrets.RANDOM}
    kept = tenant_secrets.resolve(wanted, {"made-up": "old"}, rotate=False)
    assert kept == {"fixed": "value", "made-up": "old"}
    rotated = tenant_secrets.resolve(wanted, {"made-up": "old"}, rotate=True)
    assert rotated["made-up"] != "old" and len(rotated["made-up"]) >= 40


def test_a_secret_setting_without_a_laptop_value_is_refused():
    release = {**RELEASES["triage"], "values": {**RELEASES["triage"]["values"]}}
    release["values"]["secretSettings"] = {"secretName": "s", "keys": ["SOMETHING_ELSE"]}
    with pytest.raises(SystemExit, match="SOMETHING_ELSE"):
        tenant_secrets.plan(release)


def test_secret_manifests_carry_values_only_base64_encoded():
    text = tenant_secrets.manifest("triage", "triage-settings", {"COSMOS_KEY": "plain-value"}, "triage")
    assert "plain-value" not in text and '"platform.lab/managed": "true"' in text


# --- the live check's log reading ------------------------------------------------------------------------------


def test_the_check_reads_the_worker_s_log_line():
    log = (
        "info: Function.triage_ticket.User[0]\n"
        "      Triaged M3-E02-120000: category=cards priority=high floor=False injection=False sources=3 "
        "latency_ms=812 attempt=1\n"
    )
    (m,) = check_triage.TRIAGED.finditer(log)
    assert (m["id"], m["category"], m["priority"]) == ("M3-E02-120000", "cards", "high")


def test_the_check_s_cases_cover_both_emails_and_no_email():
    wanted = {case: email for case, (_, _, email) in check_triage.CASES.items()}
    assert wanted == {"E02": "[HIGH]", "E03": None, "E14": "[REVIEW]"}


def test_rendered_file_names_match_releases():
    assert {Path(p).stem for p in render_tenants.OUT.glob("*.yaml")} == set(RELEASES)


def test_pinning_writes_the_commit_quoted_and_the_digest():
    import pin_release

    text = (ROOT / "platform/releases/triage.yaml").read_text(encoding="utf-8")
    ref, digest = "1" * 40, "sha256:" + "b" * 64
    out = yaml.safe_load(pin_release.pinned(text, ref, digest))
    assert out["chart"]["ref"] == ref and out["values"]["image"]["digest"] == digest  # a string, not a number
    with pytest.raises(SystemExit):
        pin_release.pinned("chart:\n  ref: main\n", ref, digest)


def test_a_render_with_another_helm_version_is_refused(monkeypatch):
    monkeypatch.setattr(render_tenants, "helm_version", lambda: "v4.0.0")
    with pytest.raises(SystemExit, match="renders are made with helm"):
        render_tenants.render(RELEASES["triage"])
