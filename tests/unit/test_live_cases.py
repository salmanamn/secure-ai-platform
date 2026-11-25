"""scripts/live_cases.py decides from kubectl's answer; these tests feed it the answers a cluster gives."""

import subprocess

import build_policy
import live_cases
import pytest

RULES = {r.directory.name: r for r in build_policy.load_rules()}
DENIED = (
    'Error from server (Forbidden): error when creating "{file}": admission webhook "validation.gatekeeper.sh" '
    "denied the request: {reasons}"
)


def case(rule: str, name: str) -> build_policy.Case:
    (found,) = [c for c in RULES[rule].cases if c.name == name]
    return found


def answer(monkeypatch, returncode: int, stderr: str = "", stdout: str = "") -> None:
    def fake(context, *args):
        return subprocess.CompletedProcess(["kubectl", *args], returncode, stdout, stderr)

    monkeypatch.setattr(live_cases, "kubectl", fake)


def test_allowed_and_admitted(monkeypatch):
    answer(monkeypatch, 0, stdout="pod/case-image-tag created (server dry run)")
    assert live_cases.check(None, RULES["allowed-images"], case("allowed-images", "allowed-tag")) == (True, "admitted")


def test_allowed_but_denied(monkeypatch):
    answer(monkeypatch, 1, DENIED.format(file="x", reasons="[platform-no-sa-token] Pod <x> must set ..."))
    ok, what = live_cases.check(None, RULES["allowed-images"], case("allowed-images", "allowed-tag"))
    assert not ok and "platform-no-sa-token" in what


def test_denied_by_its_own_constraint(monkeypatch):
    reason = "[platform-allowed-images] container <app> image <ghcr.io/salmanamn/app:latest> names no version: use..."
    answer(monkeypatch, 1, DENIED.format(file="x", reasons=reason))
    rule = RULES["allowed-images"]
    assert live_cases.check(None, rule, case("allowed-images", "disallowed-latest")) == (
        True,
        "denied by platform-allowed-images",
    )


@pytest.mark.parametrize(
    ("returncode", "stderr", "expected"),
    [
        (0, "", "admitted"),
        (1, 'pods "x" is forbidden: violates PodSecurity "restricted:latest": runAsNonRoot', "Pod Security"),
        (
            1,
            DENIED.format(file="x", reasons="[platform-allowed-images] names no version\n[platform-no-sa-token] ..."),
            "expected platform-allowed-images alone",
        ),
        (1, DENIED.format(file="x", reasons="[platform-allowed-images] something else"), "no message matches"),
        (1, 'namespaces "triage" not found', "something else"),
    ],
)
def test_denied_for_the_wrong_reason_is_a_failure(monkeypatch, returncode, stderr, expected):
    answer(monkeypatch, returncode, stderr)
    ok, what = live_cases.check(None, RULES["allowed-images"], case("allowed-images", "disallowed-latest"))
    assert not ok and expected in what
