# Issue tracker: Local Markdown

Issues and specs for this repo live as markdown files in `.scratch/`.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- The spec is `.scratch/<feature-slug>/spec.md`
- Implementation issues are one file per ticket at `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`, never a single combined tickets file
- Triage / workflow state is recorded as a `Status:` line near the top of each issue file (see `triage-labels.md`, plus the workflow values below)
- Comments and conversation history append to the bottom of the file under a `## Comments` heading

## Kanban (detection-tool and other efforts)

Refresh the board from ticket files:

```text
madu-darts kanban
madu-darts kanban --effort detection-tool
```

That writes `.scratch/<effort>/kanban.md`. Columns are derived from `Status:` and whether `Blocked by:` tickets are `resolved`:

| Column | Status values |
| --- | --- |
| To do | `ready-for-agent`, `ready-for-human`, `needs-triage`, `needs-info` (and unblocked) |
| Blocked | any open status whose blockers are not all `resolved` |
| Doing | `claimed` |
| In testing | `in-testing` — implementation in; live Board / human check pending |
| Done | `resolved`, `wontfix` |

After an agent lands code that still needs a live Board check, set `Status: in-testing` (not `resolved`). Move to `resolved` only after that check (or an explicit decision that offline proof is enough).

## When a skill says "publish to the issue tracker"

Create a new file under `.scratch/<feature-slug>/` (creating the directory if needed).

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The user will normally pass the path or the issue number directly.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a file with one **child** file per ticket.

- **Map**: `.scratch/<effort>/map.md` (the Notes / Decisions-so-far / Fog body).
- **Child ticket**: `.scratch/<effort>/issues/NN-<slug>.md`, numbered from `01`, with the question in the body. A `Type:` line records the ticket type (`research`/`prototype`/`grilling`/`task`); a `Status:` line records `claimed`/`resolved`.
- **Blocking**: a `Blocked by: NN, NN` line near the top. A ticket is unblocked when every file it lists is `resolved`.
- **Frontier**: scan `.scratch/<effort>/issues/` for files that are open, unblocked, and unclaimed; first by number wins.
- **Claim**: set `Status: claimed` and save before any work.
- **Resolve**: append the answer under an `## Answer` heading, set `Status: resolved`, then append a context pointer (gist + link) to the map's Decisions-so-far in `map.md`.
