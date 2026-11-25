"""Build the Gatekeeper policy (D5): ConstraintTemplates and the gator test suite, generated from the rule sources.

uv run python scripts/build_policy.py            write policy/gatekeeper/templates/*.yaml and suite.yaml
uv run python scripts/build_policy.py --check    exit 1 if a generated file is not what the sources give

Sources, one directory per rule under policy/gatekeeper/rules/<rule>/:
- rule.yaml        kind, title, description, parameters (the OpenAPI schema of the constraint's parameters)
- rule.rego        the Rego; it may import data.lib.<name> from policy/gatekeeper/lib/<name>.rego
- constraint.yaml  the Constraint applied to clusters: match, enforcement action, parameter values
- cases/*.yaml     one Kubernetes object per file: allowed-*.yaml must pass; disallowed-*.yaml must be denied with a
                   message matching its annotation test.platform.lab/expect (a regular expression)

The same generated templates go to every cluster (Gatekeeper on minikube; on AKS as Azure Policy custom definitions,
M6), and the same cases are checked three ways: by regopy in the unit tests, by gator in CI, and against a live
cluster by scripts/live_cases.py. Generated files are committed and never edited by hand.
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "policy" / "gatekeeper"
EXPECT = "test.platform.lab/expect"
TARGET = "admission.k8s.gatekeeper.sh"


@dataclass(frozen=True)
class Case:
    name: str  # file name without .yaml
    path: Path
    obj: dict

    @property
    def allowed(self) -> bool:
        return self.name.startswith("allowed-")

    @property
    def expect(self) -> str | None:
        return (self.obj.get("metadata", {}).get("annotations") or {}).get(EXPECT)


@dataclass(frozen=True)
class Rule:
    directory: Path
    meta: dict
    rego: str
    constraint: dict
    cases: list[Case]

    @property
    def kind(self) -> str:
        return self.meta["kind"]

    @property
    def template_name(self) -> str:
        return self.kind.lower()  # Gatekeeper requires metadata.name == lower-case kind

    @property
    def template_path(self) -> Path:
        return POLICY / "templates" / f"{self.template_name}.yaml"


def libs(policy: Path = POLICY) -> list[str]:
    return [p.read_text(encoding="utf-8") for p in sorted((policy / "lib").glob("*.rego"))]


def load_rules(policy: Path = POLICY) -> list[Rule]:
    rules = []
    for directory in sorted(p for p in (policy / "rules").iterdir() if p.is_dir()):
        cases = [
            Case(name=p.stem, path=p, obj=yaml.safe_load(p.read_text(encoding="utf-8")))
            for p in sorted((directory / "cases").glob("*.yaml"))
        ]
        rules.append(
            Rule(
                directory=directory,
                meta=yaml.safe_load((directory / "rule.yaml").read_text(encoding="utf-8")),
                rego=(directory / "rule.rego").read_text(encoding="utf-8"),
                constraint=yaml.safe_load((directory / "constraint.yaml").read_text(encoding="utf-8")),
                cases=cases,
            )
        )
    return rules


class _Dumper(yaml.SafeDumper):
    pass


def _str(dumper: yaml.SafeDumper, value: str) -> yaml.Node:
    style = "|" if "\n" in value else None  # Rego stays readable in the template
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_Dumper.add_representer(str, _str)


def dump(document: dict) -> str:
    return yaml.dump(document, Dumper=_Dumper, sort_keys=False, width=1000, allow_unicode=True)


def template(rule: Rule, lib_sources: list[str]) -> dict:
    parameters = rule.meta.get("parameters") or {}
    validation = {"openAPIV3Schema": {"type": "object", "properties": parameters}} if parameters else {}
    target = {"target": TARGET, "rego": rule.rego}
    used = [lib for lib in lib_sources if f"data.{lib.split()[1]}" in rule.rego]  # "package lib.x" -> data.lib.x
    if used:
        target["libs"] = used
    return {
        "apiVersion": "templates.gatekeeper.sh/v1",
        "kind": "ConstraintTemplate",
        "metadata": {
            "name": rule.template_name,
            "annotations": {
                "metadata.gatekeeper.sh/title": rule.meta["title"],
                "description": rule.meta["description"],
            },
        },
        "spec": {
            "crd": {"spec": {"names": {"kind": rule.kind}, **({"validation": validation} if validation else {})}},
            "targets": [target],
        },
    }


def suite(rules: list[Rule], policy: Path = POLICY) -> dict:
    tests = []
    for rule in rules:
        cases = []
        for case in rule.cases:
            assertion = {"violations": "no"} if case.allowed else {"violations": "yes", "message": case.expect}
            cases.append({"name": case.name, "object": str(case.path.relative_to(policy)), "assertions": [assertion]})
        tests.append(
            {
                "name": rule.directory.name,
                "template": str(rule.template_path.relative_to(POLICY)),
                "constraint": str((rule.directory / "constraint.yaml").relative_to(policy)),
                "cases": cases,
            }
        )
    return {
        "kind": "Suite",
        "apiVersion": "test.gatekeeper.sh/v1alpha1",
        "metadata": {"name": "platform-policy"},
        "tests": tests,
    }


HEADER = "# Generated by scripts/build_policy.py from {source}: don't edit by hand.\n"


def outputs(policy: Path = POLICY) -> dict[Path, str]:
    """Every generated file and its content."""
    rules = load_rules(policy)
    lib_sources = libs(policy)
    files = {}
    for rule in rules:
        source = rule.directory.relative_to(policy.parents[1])
        path = policy / "templates" / f"{rule.template_name}.yaml"
        files[path] = HEADER.format(source=source) + dump(template(rule, lib_sources))
    files[policy / "suite.yaml"] = HEADER.format(source="policy/gatekeeper/rules") + dump(suite(rules, policy))
    return files


def problems(rules: list[Rule]) -> list[str]:
    """Rules the generator refuses: no case of one kind, a disallowed case without its expectation, a mismatch."""
    found = []
    for rule in rules:
        name = rule.directory.name
        if rule.constraint.get("kind") != rule.kind:
            found.append(f"{name}: constraint kind {rule.constraint.get('kind')} is not {rule.kind}")
        if not any(c.allowed for c in rule.cases) or all(c.allowed for c in rule.cases):
            found.append(f"{name}: needs at least one allowed-*.yaml and one disallowed-*.yaml case")
        for case in rule.cases:
            if not case.name.startswith(("allowed-", "disallowed-")):
                found.append(f"{name}: case {case.name} must start with allowed- or disallowed-")
            if not case.allowed and not case.expect:
                found.append(f"{name}: {case.name} has no {EXPECT} annotation")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="compare with the generated files, write nothing")
    args = parser.parse_args()
    errors = problems(load_rules())
    for error in errors:
        print(f"FAIL {error}")
    if errors:
        return 1
    files = outputs()
    stale = [p for p, text in files.items() if not p.is_file() or p.read_text(encoding="utf-8") != text]
    expected_templates = {p for p in files if p.parent.name == "templates"}
    extra = sorted(set((POLICY / "templates").glob("*.yaml")) - expected_templates)
    if args.check:
        for path in stale:
            print(f"FAIL {path.relative_to(ROOT)} is stale: run uv run python scripts/build_policy.py")
        for path in extra:
            print(f"FAIL {path.relative_to(ROOT)} has no rule directory: delete it")
        if stale or extra:
            return 1
        print(f"OK   {len(files) - 1} templates and the suite are up to date")
        return 0
    (POLICY / "templates").mkdir(exist_ok=True)
    for path in extra:
        path.unlink()
    for path, text in files.items():
        path.write_text(text, encoding="utf-8")
    cases = sum(len(r.cases) for r in load_rules())
    print(f"wrote {len(files) - 1} templates and policy/gatekeeper/suite.yaml ({cases} cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
