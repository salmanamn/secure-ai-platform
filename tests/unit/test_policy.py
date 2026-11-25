"""The Gatekeeper policy (D5): the Rego inside the generated templates, evaluated with regopy on every case.

What runs here is what ships: each test reads the ConstraintTemplate that scripts/build_policy.py wrote, takes its
Rego and libs, and evaluates them on each case file with the constraint's parameters, the way Gatekeeper builds its
input (input.review.object, input.parameters). The constraint's match (kinds, excludedNamespaces) is applied first,
as Gatekeeper does. gator (CI, D5) and the live cluster (scripts/live_cases.py) check the same cases again.
"""

import json
import re

import build_policy
import pytest
import yaml
from regopy import Interpreter

RULES = build_policy.load_rules()
CASES = [(rule, case) for rule in RULES for case in rule.cases]


def group_of(api_version: str) -> str:
    return api_version.split("/")[0] if "/" in api_version else ""


def matches(constraint: dict, obj: dict) -> bool:
    """The parts of Gatekeeper's match this policy uses: kinds and excludedNamespaces."""
    match = constraint["spec"].get("match", {})
    group = group_of(obj["apiVersion"])
    kinds = match.get("kinds")
    if kinds and not any(group in k["apiGroups"] and obj["kind"] in k["kinds"] for k in kinds):
        return False
    meta = obj.get("metadata", {})
    namespace = meta.get("name") if obj["kind"] == "Namespace" else meta.get("namespace", "")
    return namespace not in match.get("excludedNamespaces", [])


def violations(rule: build_policy.Rule, obj: dict) -> list[str]:
    if not matches(rule.constraint, obj):
        return []
    template = yaml.safe_load(rule.template_path.read_text(encoding="utf-8"))
    target = template["spec"]["targets"][0]
    rego = Interpreter()
    for i, lib in enumerate(target.get("libs", [])):
        rego.add_module(f"lib{i}", lib)
    rego.add_module("rule", target["rego"])
    package = target["rego"].split()[1]
    rego.set_input(
        {
            "review": {
                "object": obj,
                "kind": {"group": group_of(obj["apiVersion"]), "kind": obj["kind"]},
                "operation": "CREATE",
            },
            "parameters": rule.constraint["spec"].get("parameters", {}),
        }
    )
    result = json.loads(str(rego.query(f"x := data.{package}.violation")))
    return sorted(v["msg"] for v in result["bindings"]["x"])


@pytest.mark.parametrize(("rule", "case"), CASES, ids=[f"{r.directory.name}/{c.name}" for r, c in CASES])
def test_case(rule, case):
    found = violations(rule, case.obj)
    if case.allowed:
        assert found == []
    else:
        assert found, "expected a violation, got none"
        assert any(re.search(case.expect, msg) for msg in found), f"no message matches {case.expect!r}: {found}"


def test_generated_files_are_up_to_date():
    for path, text in build_policy.outputs().items():
        assert path.read_text(encoding="utf-8") == text, f"{path.name} is stale: run scripts/build_policy.py"


def test_every_rule_has_both_kinds_of_case_and_expectations():
    assert build_policy.problems(RULES) == []
    assert len(RULES) == 4


def test_every_constraint_denies():
    # dryrun or warn would let everything through; a rule is only enforced when its constraint says deny
    assert {r.constraint["spec"]["enforcementAction"] for r in RULES} == {"deny"}


def test_registry_prefixes_end_with_a_slash():
    (rule,) = [r for r in RULES if r.kind == "K8sPlatformAllowedImages"]
    registries = rule.constraint["spec"]["parameters"]["registries"]
    assert registries and all(r.endswith("/") for r in registries)


def test_tenant_namespaces_on_the_platform_are_compliant():
    """platform/namespaces/tenants.yaml passes the namespace rule (it is applied after the constraints, M1 Part 2)."""
    (rule,) = [r for r in RULES if r.kind == "K8sPlatformTenantNamespace"]
    tenants = list(yaml.safe_load_all((build_policy.ROOT / "platform/namespaces/tenants.yaml").read_text()))
    assert [t["metadata"]["name"] for t in tenants] == ["triage", "voice", "meetings"]
    for namespace in tenants:
        assert violations(rule, namespace) == []


def test_webhook_sees_exactly_what_the_constraints_judge():
    """platform/gatekeeper/values.yaml (D10): no wildcard, and every kind a constraint matches reaches Gatekeeper."""
    values = yaml.safe_load((build_policy.ROOT / "platform/gatekeeper/values.yaml").read_text())
    rules = values["validatingWebhookCustomRules"]
    sent = {
        (group, resource)
        for r in rules
        if {"CREATE", "UPDATE"} <= set(r["operations"])
        for group in r["apiGroups"]
        for resource in r["resources"]
    }
    assert not any("*" in g or "*" in res for g, res in sent)
    judged = {
        (group, f"{kind.lower()}s")
        for rule in RULES
        for k in rule.constraint["spec"]["match"]["kinds"]
        for group in k["apiGroups"]
        for kind in k["kinds"]
    }
    assert judged <= sent, f"constraints judge kinds the webhook never sends: {sorted(judged - sent)}"
    assert sent - judged == {("", "pods/ephemeralcontainers")}  # kubectl debug (D6); nothing else beyond the rules
