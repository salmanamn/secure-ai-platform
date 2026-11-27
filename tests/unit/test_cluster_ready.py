"""The live checks refuse an API server that isn't answering, before the run and before writing evidence (D21)."""

import subprocess

import build_policy
import check_tenancy
import cluster_ready
import live_cases
import pytest

REFUSED = "The connection to the server 127.0.0.1:32771 was refused - did you specify the right host or port?"


def kubectl_answering(ready: list[bool]):
    """A fake kubectl: /readyz answers ok while ready[0] is True (pop one value per call), everything else succeeds."""
    calls = []

    def fake(context, *args, stdin=None):
        calls.append(args)
        if args == cluster_ready.READYZ:
            if ready.pop(0):
                return subprocess.CompletedProcess(args, 0, "ok", "")
            return subprocess.CompletedProcess(args, 1, "", REFUSED)
        return subprocess.CompletedProcess(args, 0, "{}" if args[0] == "version" else "yes", "")

    fake.calls = calls
    return fake


@pytest.mark.parametrize(
    ("returncode", "stdout", "stderr", "reason"),
    [
        (0, "ok\n", "", None),
        (1, "", REFUSED, REFUSED),
        (0, "[-]etcd failed: reason withheld\nreadyz check failed", "", "readyz check failed"),
        (1, "", "", "exit status 1"),
    ],
)
def test_not_ready(returncode, stdout, stderr, reason):
    def fake(context, *args):
        return subprocess.CompletedProcess(args, returncode, stdout, stderr)

    assert cluster_ready.not_ready(fake, None) == reason


def test_live_cases_refuse_to_start(monkeypatch, tmp_path):
    fake = kubectl_answering([False])
    monkeypatch.setattr(live_cases, "kubectl", fake)
    evidence = tmp_path / "admission.txt"
    monkeypatch.setattr("sys.argv", ["live_cases.py", "--evidence", str(evidence)])
    assert live_cases.main() == 2
    assert fake.calls == [cluster_ready.READYZ]  # no case was sent
    assert not evidence.exists()


def test_live_cases_write_no_evidence_when_the_cluster_drops(monkeypatch, tmp_path):
    monkeypatch.setattr(live_cases, "kubectl", kubectl_answering([True, False]))
    monkeypatch.setattr(live_cases, "check", lambda context, rule, case: (True, "admitted"))
    evidence = tmp_path / "admission.txt"
    monkeypatch.setattr("sys.argv", ["live_cases.py", "--evidence", str(evidence)])
    assert live_cases.main() == 2
    assert not evidence.exists()


def test_live_cases_write_evidence_when_the_cluster_answered_throughout(monkeypatch, tmp_path):
    monkeypatch.setattr(live_cases, "kubectl", kubectl_answering([True, True]))
    monkeypatch.setattr(live_cases, "check", lambda context, rule, case: (True, "admitted"))
    evidence = tmp_path / "admission.txt"
    monkeypatch.setattr("sys.argv", ["live_cases.py", "--evidence", str(evidence)])
    assert live_cases.main() == 0
    cases = sum(len(r.cases) for r in build_policy.load_rules())
    assert evidence.read_text().rstrip().endswith(f"{cases}/{cases} cases as expected")


def test_check_tenancy_refuses_to_start(monkeypatch, tmp_path):
    fake = kubectl_answering([False])
    monkeypatch.setattr(check_tenancy, "kubectl", fake)
    evidence = tmp_path / "tenancy.txt"
    monkeypatch.setattr("sys.argv", ["check_tenancy.py", "--only", "rbac", "--evidence", str(evidence)])
    assert check_tenancy.main() == 2
    assert fake.calls == [cluster_ready.READYZ]
    assert not evidence.exists()


def test_check_tenancy_writes_no_evidence_when_the_cluster_drops(monkeypatch, tmp_path):
    monkeypatch.setattr(check_tenancy, "kubectl", kubectl_answering([True, False]))
    evidence = tmp_path / "tenancy.txt"
    monkeypatch.setattr("sys.argv", ["check_tenancy.py", "--only", "admission", "--evidence", str(evidence)])
    assert check_tenancy.main() == 2
    assert not evidence.exists()
