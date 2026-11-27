"""Is the API server answering? The live checks ask before they start and again before they write evidence (D21).

Twice a cluster dropped in the middle of a run (M1 once, M2 once): every check after that point failed with a
connection error, and the evidence file looked like real results. So a live check refuses to start when the API
server is not ready, and refuses to write evidence when it stopped answering before the end.
"""

from collections.abc import Callable
from subprocess import CompletedProcess

READYZ = ("get", "--raw", "/readyz")

Kubectl = Callable[..., CompletedProcess]


def not_ready(kubectl: Kubectl, context: str | None) -> str | None:
    """None when `kubectl get --raw /readyz` answers ok, else the reason (one line)."""
    result = kubectl(context, *READYZ)
    if result.returncode == 0 and result.stdout.strip() == "ok":
        return None
    text = (result.stderr or result.stdout or "").strip().splitlines()
    return text[-1] if text else f"exit status {result.returncode}"


def refuse_start(kubectl: Kubectl, context: str | None) -> str | None:
    """The line to print (and exit 2 with) when the cluster can't be checked; None to go on."""
    reason = not_ready(kubectl, context)
    if reason is None:
        return None
    return f"FAIL the API server is not ready ({reason}): nothing checked, no evidence written"


def refuse_evidence(kubectl: Kubectl, context: str | None) -> str | None:
    """The line to print (and exit 2 with) when the cluster stopped answering during the run; None to go on."""
    reason = not_ready(kubectl, context)
    if reason is None:
        return None
    return (
        f"FAIL the API server stopped answering during the run ({reason}): "
        "the lines above are not evidence, none written"
    )
