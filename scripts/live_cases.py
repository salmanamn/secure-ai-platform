"""Every policy case against a live cluster (D5): the third check, after regopy (unit tests) and gator (CI).

Each case file goes through `kubectl apply --dry-run=server`: the API server runs every admission step (Gatekeeper,
Pod Security Admission, validation) and stores nothing. An allowed-*.yaml case must be admitted; a disallowed-*.yaml
case must be denied by its own rule's constraint alone (its name in brackets in the message, no other platform
constraint named, its expectation matched), so a case that fails for the wrong reason is reported as wrong.

uv run python scripts/live_cases.py [--context NAME] [--evidence docs/evidence/m1-admission.txt]

Exit 2, with nothing written, when the API server is not ready before the run or stopped answering during it (D21).

The evidence file names cases and constraints only, never images or messages (a Project 4 lesson: no `@` in evidence).
"""

import argparse
import datetime
import json
import re
import subprocess
import sys

import build_policy
import cluster_ready

PLATFORM_CONSTRAINT = re.compile(r"\[(platform-[a-z-]+)\]")


def kubectl(context: str | None, *args: str) -> subprocess.CompletedProcess:
    base = ["kubectl", *(["--context", context] if context else [])]
    return subprocess.run([*base, *args], capture_output=True, text=True, check=False)


def check(context: str | None, rule: build_policy.Rule, case: build_policy.Case) -> tuple[bool, str]:
    result = kubectl(context, "apply", "--dry-run=server", "-f", str(case.path))
    output = result.stdout + result.stderr
    named = set(PLATFORM_CONSTRAINT.findall(output))
    own = rule.constraint["metadata"]["name"]
    if case.allowed:
        if result.returncode == 0:
            return True, "admitted"
        return False, f"denied ({', '.join(sorted(named)) or 'not by a platform constraint'})"
    if result.returncode == 0:
        return False, "admitted"
    if "violates PodSecurity" in output:
        return False, "denied by Pod Security Admission, not by its rule"
    if named != {own}:
        return False, f"denied by {', '.join(sorted(named)) or 'something else'}, expected {own} alone"
    if not re.search(case.expect, output):
        return False, f"denied by {own}, but no message matches the case's expectation"
    return True, f"denied by {own}"


def describe(context: str | None) -> list[str]:
    version = json.loads(kubectl(context, "version", "-o", "json").stdout or "{}")
    image = kubectl(
        context,
        "-n",
        "gatekeeper-system",
        "get",
        "deploy/gatekeeper-controller-manager",
        "-o",
        "jsonpath={.spec.template.spec.containers[0].image}",
    ).stdout
    current = kubectl(context, "config", "current-context").stdout.strip()
    return [
        f"date: {datetime.datetime.now(datetime.UTC):%Y-%m-%dT%H:%MZ}",
        f"context: {context or current}",
        f"server: {version.get('serverVersion', {}).get('gitVersion', 'unknown')}",
        f"gatekeeper: {image.rsplit('/', 1)[-1] or 'not found'}",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--context", help="kubectl context (default: the current one)")
    parser.add_argument("--evidence", help="also write the result to this file")
    args = parser.parse_args()
    if refusal := cluster_ready.refuse_start(kubectl, args.context):
        print(refusal)
        return 2

    lines = describe(args.context)
    failures = 0
    total = 0
    for rule in build_policy.load_rules():
        for case in rule.cases:
            total += 1
            ok, what = check(args.context, rule, case)
            failures += not ok
            lines.append(f"{'OK  ' if ok else 'FAIL'} {rule.directory.name}/{case.name}: {what}")
    lines.append(f"{total - failures}/{total} cases as expected" if not failures else f"FAIL {failures} of {total}")
    print("\n".join(lines))
    if refusal := cluster_ready.refuse_evidence(kubectl, args.context):
        print(refusal)
        return 2
    if args.evidence:
        with open(args.evidence, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        print(f"wrote {args.evidence}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
