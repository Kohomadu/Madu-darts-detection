"""Kanban board from local markdown tickets under ``.scratch/<effort>/issues/``.

Status on each ticket file is the source of truth. Columns:

* **To do** — ready / triage / human work, unblocked
* **Blocked** — open, but a listed blocker is not ``resolved``
* **Doing** — ``claimed``
* **In testing** — ``in-testing`` (code in; live Board check pending)
* **Done** — ``resolved``
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

COLUMNS = ("todo", "blocked", "doing", "in-testing", "done")
COLUMN_TITLES = {
    "todo": "To do",
    "blocked": "Blocked",
    "doing": "Doing",
    "in-testing": "In testing",
    "done": "Done",
}

_STATUS_RE = re.compile(r"(?im)^(?:\*\*)?Status:(?:\*\*)?[ \t]*(\S+)")
# Same-line only: an empty ``Blocked by:`` must not swallow the title (``2.1.0`` → fake 2,1,0).
_BLOCKED_RE = re.compile(r"(?im)^(?:\*\*)?Blocked by:(?:\*\*)?[ \t]*(.*)$")
_TITLE_RE = re.compile(r"(?m)^#\s+(\d+):\s*(.+)$")
_TITLE_ALT_RE = re.compile(r"(?m)^#\s+(.+)$")
_NUM_FROM_NAME = re.compile(r"^(\d+)-")

# Workflow statuses (kanban). Triage labels from docs/agents/triage-labels.md also appear.
_DONE = frozenset({"resolved", "wontfix"})
_DOING = frozenset({"claimed"})
_TESTING = frozenset({"in-testing"})
_OPEN = frozenset(
    {
        "ready-for-agent",
        "ready-for-human",
        "needs-triage",
        "needs-info",
        "in-testing",
        "claimed",
    }
)


@dataclass(frozen=True)
class TicketCard:
    number: int
    title: str
    status: str
    blocked_by: tuple[int, ...]
    path: Path
    column: str

    @property
    def label(self) -> str:
        return f"{self.number}: {self.title}"


def _parse_blockers(raw: str) -> tuple[int, ...]:
    text = raw.strip()
    if not text or text.lower().startswith("none"):
        return ()
    nums = re.findall(r"\b(\d+)\b", text)
    # Drop non-ticket noise like "spiderweb-manual-bind" — only pure numbers count.
    return tuple(int(n) for n in nums)


def parse_ticket(path: Path) -> TicketCard | None:
    text = path.read_text(encoding="utf-8")
    status_m = _STATUS_RE.search(text)
    status = (status_m.group(1).strip().lower() if status_m else "needs-triage").rstrip("*")
    blocked_m = _BLOCKED_RE.search(text)
    blocked_by = _parse_blockers(blocked_m.group(1) if blocked_m else "")

    title_m = _TITLE_RE.search(text)
    if title_m:
        number = int(title_m.group(1))
        title = title_m.group(2).strip()
    else:
        name_m = _NUM_FROM_NAME.match(path.name)
        if not name_m:
            return None
        number = int(name_m.group(1))
        alt = _TITLE_ALT_RE.search(text)
        title = alt.group(1).strip() if alt else path.stem

    return TicketCard(
        number=number,
        title=title,
        status=status,
        blocked_by=blocked_by,
        path=path,
        column="",  # filled in board()
    )


def _column_for(card: TicketCard, resolved: set[int]) -> str:
    if card.status in _DONE:
        return "done"
    if card.status in _DOING:
        return "doing"
    if card.status in _TESTING:
        return "in-testing"
    open_blockers = [b for b in card.blocked_by if b not in resolved]
    if open_blockers:
        return "blocked"
    return "todo"


def load_tickets(issues_dir: Path) -> list[TicketCard]:
    cards: list[TicketCard] = []
    for path in sorted(issues_dir.glob("*.md")):
        card = parse_ticket(path)
        if card is not None:
            cards.append(card)
    resolved = {c.number for c in cards if c.status in _DONE}
    return [
        TicketCard(
            number=c.number,
            title=c.title,
            status=c.status,
            blocked_by=c.blocked_by,
            path=c.path,
            column=_column_for(c, resolved),
        )
        for c in cards
    ]


def group_by_column(cards: list[TicketCard]) -> dict[str, list[TicketCard]]:
    out: dict[str, list[TicketCard]] = {col: [] for col in COLUMNS}
    for card in sorted(cards, key=lambda c: c.number):
        out.setdefault(card.column, []).append(card)
    return out


def format_markdown(cards: list[TicketCard], *, effort: str) -> str:
    groups = group_by_column(cards)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Kanban — {effort}",
        "",
        f"Generated {now} from ticket `Status:` / `Blocked by:` lines. "
        f"Refresh with `madu-darts kanban`.",
        "",
        "| Column | Meaning |",
        "| --- | --- |",
        "| To do | Unblocked, not started (`ready-for-agent`, `ready-for-human`, `needs-triage`, …) |",
        "| Blocked | Open, but a listed blocker is not `resolved` |",
        "| Doing | `claimed` |",
        "| In testing | `in-testing` — code in; live Board check pending |",
        "| Done | `resolved` (or `wontfix`) |",
        "",
    ]
    for col in COLUMNS:
        items = groups.get(col, [])
        lines.append(f"## {COLUMN_TITLES[col]} ({len(items)})")
        lines.append("")
        if not items:
            lines.append("_empty_")
            lines.append("")
            continue
        for card in items:
            block = ""
            if card.blocked_by and col == "blocked":
                block = f" — waiting on {', '.join(str(b) for b in card.blocked_by)}"
            lines.append(f"- [{card.label}]({card.path.name}) `{card.status}`{block}")
        lines.append("")
    return "\n".join(lines)


def write_board(issues_dir: Path, out_path: Path | None = None) -> Path:
    effort = issues_dir.parent.name
    cards = load_tickets(issues_dir)
    target = out_path or (issues_dir.parent / "kanban.md")
    target.write_text(format_markdown(cards, effort=effort), encoding="utf-8")
    return target


def board_snapshot(issues_dir: Path) -> dict[str, list[dict[str, object]]]:
    """JSON-able columns for a canvas or API."""
    groups = group_by_column(load_tickets(issues_dir))
    return {
        col: [
            {
                "number": c.number,
                "title": c.title,
                "status": c.status,
                "blockedBy": list(c.blocked_by),
            }
            for c in groups[col]
        ]
        for col in COLUMNS
    }
