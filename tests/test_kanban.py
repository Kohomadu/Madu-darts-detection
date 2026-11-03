"""Kanban columns from ticket Status / Blocked by lines."""

from __future__ import annotations

from pathlib import Path

from madu_darts.kanban import group_by_column, load_tickets, write_board


def test_empty_blocked_by_does_not_parse_title_numbers(tmp_path: Path) -> None:
    issues = tmp_path / "issues"
    issues.mkdir()
    (issues / "06-schema.md").write_text(
        "Status: resolved\nBlocked by:\n\n# Confirm live throw schema on Autodarts 2.1.0\n",
        encoding="utf-8",
    )
    card = load_tickets(issues)[0]
    assert card.blocked_by == ()
    assert card.column == "done"


def test_kanban_places_in_testing_and_blocked(tmp_path: Path) -> None:
    issues = tmp_path / "issues"
    issues.mkdir()
    (issues / "10-done.md").write_text(
        "Status: resolved\nBlocked by:\n\n# 10: Done ticket\n",
        encoding="utf-8",
    )
    (issues / "20-waiting.md").write_text(
        "**Status:** ready-for-agent\n**Blocked by:** 99\n\n# 20: Waiting on missing\n",
        encoding="utf-8",
    )
    (issues / "30-test.md").write_text(
        "**Status:** in-testing\n**Blocked by:** None\n\n# 30: Live check\n",
        encoding="utf-8",
    )
    (issues / "40-ready.md").write_text(
        "Status: ready-for-agent\nBlocked by: 10\n\n# 40: Unblocked by resolved\n",
        encoding="utf-8",
    )
    cards = load_tickets(issues)
    groups = group_by_column(cards)
    assert [c.number for c in groups["done"]] == [10]
    assert [c.number for c in groups["blocked"]] == [20]
    assert [c.number for c in groups["in-testing"]] == [30]
    assert [c.number for c in groups["todo"]] == [40]
    out = write_board(issues, tmp_path / "kanban.md")
    text = out.read_text(encoding="utf-8")
    assert "## In testing (1)" in text
    assert "30: Live check" in text
