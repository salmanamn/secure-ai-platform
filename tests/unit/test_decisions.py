"""docs/decisions.md and its index (D13): numbers run D1, D2, … with no gap or repeat, and docs/decisions-index.md is
exactly what scripts/decisions_index.py generates from the headings."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("decisions_index", ROOT / "scripts" / "decisions_index.py")
index = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(index)


def decisions() -> list:
    return index.parse((ROOT / "docs" / "decisions.md").read_text(encoding="utf-8"))


def test_every_number_once_in_order():
    found = decisions()
    assert index.problems(found) == []
    assert [d.number for d in found] == list(range(1, len(found) + 1))


def test_the_index_is_generated_from_the_headings():
    current = (ROOT / "docs" / "decisions-index.md").read_text(encoding="utf-8")
    assert current == index.render(decisions()), "run: uv run python scripts/decisions_index.py"


def test_a_missing_or_repeated_number_is_found():
    text = "## D1 — One\n- a\n## D3 — Three\n- b\n## D3 — Three again\n"
    assert index.problems(index.parse(text)) == ["D3 is used twice", "D2 is missing"]


def test_updates_and_status_lines():
    text = (
        "## D1 — First\n- a\n"
        "## D2 — Second\n- **Status:** open: the owner decides\n"
        "## D3 — Third, which changes the first (updates D1)\n- c\n"
    )
    found = index.parse(text)
    assert [index.status_text(d) for d in found] == [
        "accepted; updated by D3",
        "open: the owner decides",
        "accepted; updates D1",
    ]
    assert found[2].title == "Third, which changes the first"
    assert index.problems(index.parse("## D1 — First (updates D2)\n## D2 — Second\n")) == [
        "D1 updates D2, which is not an earlier decision"
    ]


def test_links_point_at_githubs_heading_anchors():
    assert index.github_anchor("D1 — Shape: one turn, three components") == "d1--shape-one-turn-three-components"
    assert index.github_anchor("D16 — Speech to text: `stt-small`") == "d16--speech-to-text-stt-small"
    assert index.github_anchor("D53 — AKS 1.36: from 1.37") == "d53--aks-136-from-137"
