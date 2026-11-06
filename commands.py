"""The ``/recall`` slash command.

Handler contract: one ``raw_args`` string in, one display string out.
Supported forms:

- ``/recall`` — summary: due count, next due date, streak, retention.
- ``/recall due`` — the summary plus the fronts of the next few due cards.
"""

from __future__ import annotations

try:  # package import (inside Hermes) or top-level import (unit tests)
    from . import tools as _tools
except ImportError:  # pragma: no cover - exercised by the test harness
    import tools as _tools

_PREVIEW = 5


def recall_command(raw_args: str = "") -> str:
    try:
        store = _tools.get_store()
        today = _tools._today()
        stats = store.review_stats(today=today)
        due = store.due_cards(today=today)
        total = store.count_cards()
        next_due = store.next_due_date(today=today)

        if total == 0:
            return (
                "Recall: no cards yet. Ask me to remember something — "
                'e.g. "remember: git rebase -i HEAD~3 — interactively '
                'rebase the last 3 commits" — and I will quiz you on '
                "it until it sticks."
            )

        retention = stats["retention"]
        retention_txt = (
            f"{retention * 100:.0f}%" if retention is not None else "—"
        )
        lines = [
            f"Recall: {len(due)} due now · {total} cards total · "
            f"streak {stats['streak_days']}d · retention {retention_txt} · "
            f"{stats['reviewed_today']} reviewed today"
        ]
        if next_due:
            lines.append(f"Next due: {next_due}")
        elif not due:
            lines.append("Nothing due — you're all caught up.")

        args = (raw_args or "").strip().lower()
        if args.startswith("due") and due:
            lines.append("")
            lines.append("Up next:")
            for card in due[:_PREVIEW]:
                lines.append(f"  • {card['front']}  (due {card['due_date']})")
            if len(due) > _PREVIEW:
                lines.append(f"  … and {len(due) - _PREVIEW} more")
        elif due:
            lines.append("Tip: /recall due lists what's waiting.")
        return "\n".join(lines)
    except Exception as exc:  # a slash command must not crash the session
        return f"Recall: something went wrong ({exc})."
