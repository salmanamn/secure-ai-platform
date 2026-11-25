"""The decisions index (M1, D13): one line per decision of docs/decisions.md, in docs/decisions-index.md.

uv run python scripts/decisions_index.py            write docs/decisions-index.md from the headings
uv run python scripts/decisions_index.py --check    exit 1 if the index is not what the headings give, or a number
                                                    is missing, used twice or out of order

The index is never edited by hand: tests/unit/test_decisions.py runs the same check in CI's `unit` job, so a new
or renamed decision without a regenerated index fails the pull request.

What each line says:
- the number, linked to its heading (GitHub's anchor for that heading);
- the title, without a trailing "(updates Dx …)";
- the status: the decision's own `- **Status:** …` line if it has one (open questions, workarounds), otherwise
  "accepted"; plus "updates Dx" when its heading says so, and "updated by Dy" when a later heading updates it.
"""

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECISIONS = ROOT / "docs" / "decisions.md"
INDEX = ROOT / "docs" / "decisions-index.md"

HEADING = re.compile(r"^## D(\d+) — (.+)$", re.MULTILINE)
UPDATES = re.compile(r"\s*\(updates ([^)]*)\)\s*$")
STATUS = re.compile(r"^- \*\*Status:\*\* (.+)$", re.MULTILINE)
NUMBER = re.compile(r"D(\d+)")


@dataclass
class Decision:
    number: int
    heading: str  # the heading text after "## "
    title: str
    status: str
    updates: list[int] = field(default_factory=list)
    updated_by: list[int] = field(default_factory=list)


def github_anchor(heading: str) -> str:
    """The id GitHub gives a Markdown heading: lower case, punctuation removed (letters, digits, `_`, `-` and spaces
    stay), each space a hyphen. "D1 — Shape: one turn" -> "d1--shape-one-turn" (the dash goes, its spaces stay)."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def parse(text: str) -> list[Decision]:
    matches = list(HEADING.finditer(text))
    decisions = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[match.end() : end]
        title = match.group(2).strip()
        updates = []
        found = UPDATES.search(title)
        if found:
            updates = [int(n) for n in NUMBER.findall(found.group(1))]
            title = title[: found.start()].rstrip()
        status = STATUS.search(body)
        decisions.append(
            Decision(
                number=int(match.group(1)),
                heading=f"D{match.group(1)} — {match.group(2).strip()}",
                title=title,
                status=status.group(1).strip().rstrip(".") if status else "accepted",
                updates=updates,
            )
        )
    by_number = {d.number: d for d in decisions}
    for d in decisions:
        for n in d.updates:
            if n in by_number:
                by_number[n].updated_by.append(d.number)
    return decisions


def problems(decisions: list[Decision]) -> list[str]:
    """Numbers must run D1, D2, … without a gap or a repeat, and an "updates" must name an earlier decision."""
    found = []
    numbers = [d.number for d in decisions]
    if not numbers:
        return ["no decisions found (headings must look like '## D1 — Title')"]
    seen = set()
    for n in numbers:
        if n in seen:
            found.append(f"D{n} is used twice")
        seen.add(n)
    missing = sorted(set(range(1, max(numbers) + 1)) - seen)
    found += [f"D{n} is missing" for n in missing]
    if numbers != sorted(numbers):
        found.append("decisions are not in number order")
    for d in decisions:
        for n in d.updates:
            if n not in seen or n >= d.number:
                found.append(f"D{d.number} updates D{n}, which is not an earlier decision")
    return found


def status_text(d: Decision) -> str:
    parts = [d.status]
    if d.updates:
        parts.append("updates " + ", ".join(f"D{n}" for n in d.updates))
    if d.updated_by:
        parts.append("updated by " + ", ".join(f"D{n}" for n in d.updated_by))
    return "; ".join(parts)


def render(decisions: list[Decision]) -> str:
    first, last = decisions[0].number, decisions[-1].number
    explicit = sum(d.status != "accepted" for d in decisions)
    updated = sum(bool(d.updated_by) for d in decisions)
    lines = [
        "# Decisions index",
        "",
        "Generated from the headings of [decisions.md](decisions.md) by `scripts/decisions_index.py`; don't edit it by",
        "hand. `tests/unit/test_decisions.py` fails when this file and the headings disagree, or when a number is",
        "missing or used twice.",
        "",
        f"{len(decisions)} decisions (D{first}–D{last}): {updated} updated by a later one, {explicit} with a status of",
        "their own (open questions, workarounds); the rest accepted as written.",
        "",
        "| # | Decision | Status |",
        "|---|---|---|",
    ]
    for d in decisions:
        title = d.title.replace("|", "\\|")
        lines.append(f"| [D{d.number}](decisions.md#{github_anchor(d.heading)}) | {title} | {status_text(d)} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="compare with docs/decisions-index.md, write nothing")
    args = parser.parse_args()
    decisions = parse(DECISIONS.read_text(encoding="utf-8"))
    errors = problems(decisions)
    for error in errors:
        print(f"FAIL {error}")
    if errors:
        return 1
    index = render(decisions)
    if args.check:
        current = INDEX.read_text(encoding="utf-8") if INDEX.is_file() else ""
        if current != index:
            print(f"FAIL {INDEX.relative_to(ROOT)} is stale: run uv run python scripts/decisions_index.py")
            return 1
        print(f"OK   {len(decisions)} decisions, index up to date")
        return 0
    INDEX.write_text(index, encoding="utf-8")
    print(
        f"wrote {INDEX.relative_to(ROOT)}: {len(decisions)} decisions (D{decisions[0].number}–D{decisions[-1].number})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
