"""Recall tool handlers.

Every handler follows the Hermes plugin contract: signature
``handler(args: dict, **kwargs) -> str``, the return value is always a
JSON string (success and error alike), and handlers never raise — any
failure is reported as ``{"error": "..."}`` so the host can surface it
to the model instead of crashing the turn.

State lives in the SQLite database opened by Hermes'
``plugin_db("recall")`` helper (``<HERMES_HOME>/plugin-data/recall/
data.db``, WAL mode), which survives plugin updates and removal. Two
environment overrides exist purely to make the plugin testable outside
the host:

- ``RECALL_DB_PATH`` — use this SQLite file instead of ``plugin_db()``.
- ``RECALL_TODAY`` — pretend today is this ``YYYY-MM-DD`` date (used by
  the demo/tests to fast-forward the schedule deterministically).
"""

from __future__ import annotations

import datetime as _dt
import json
import os

try:  # package import (inside Hermes) or top-level import (unit tests)
    from .scheduler import apply_grade, grade_name, parse_grade
    from .store import Store
except ImportError:  # pragma: no cover - exercised by the test harness
    from scheduler import apply_grade, grade_name, parse_grade
    from store import Store

_STORE: Store | None = None


def _today() -> _dt.date:
    override = os.environ.get("RECALL_TODAY", "").strip()
    if override:
        try:
            return _dt.date.fromisoformat(override)
        except ValueError:
            pass
    return _dt.date.today()


def _fallback_db_path() -> str:
    """Path used when the host's plugin_storage is unavailable."""
    try:
        from plugins.plugin_storage import plugin_data_dir

        return str(plugin_data_dir("recall") / "data.db")
    except Exception:
        home = os.environ.get("HERMES_HOME") or os.path.join(
            os.path.expanduser("~"), ".hermes"
        )
        return os.path.join(home, "plugin-data", "recall", "data.db")


def _open_store() -> Store:
    env_path = os.environ.get("RECALL_DB_PATH", "").strip()
    if env_path:
        return Store(env_path)
    try:
        from plugins.plugin_storage import plugin_db

        return Store(connection=plugin_db("recall"))
    except Exception:
        return Store(_fallback_db_path())


def get_store() -> Store:
    """Return the process-wide store, opening the database lazily."""
    global _STORE
    if _STORE is None:
        _STORE = _open_store()
    return _STORE


def _ok(payload: dict) -> str:
    return json.dumps({"ok": True, **payload})


def _err(message: str) -> str:
    return json.dumps({"ok": False, "error": message})


def _public_card(card: dict, *, with_back: bool = True) -> dict:
    """Serialisable view of a card (drops the internal CardState)."""
    out = {
        "id": card["id"],
        "front": card["front"],
        "deck": card["deck"],
        "tags": card["tags"],
        "due_date": card["due_date"],
        "interval_days": card["interval"],
        "repetitions": card["repetitions"],
        "ease": round(card["ease"], 2),
    }
    if with_back:
        out["back"] = card["back"]
    return out


# ----------------------------------------------------------------------
# recall_add
# ----------------------------------------------------------------------


def recall_add(args: dict, **kwargs) -> str:
    """Create a flashcard. New cards are due immediately."""
    try:
        args = args or {}
        front = str(args.get("front", "")).strip()
        back = str(args.get("back", "")).strip()
        if not front or not back:
            return _err("recall_add requires non-empty 'front' and 'back'.")
        deck = str(args.get("deck", "default") or "default").strip() or "default"
        raw_tags = args.get("tags") or []
        if isinstance(raw_tags, str):
            tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
        else:
            tags = [str(t).strip() for t in raw_tags if str(t).strip()]

        store = get_store()
        duplicate = store.find_card_by_front(front)
        card = store.add_card(front, back, deck=deck, tags=tags, today=_today())
        payload = {"card": _public_card(card), "due_now": True}
        if duplicate is not None:
            payload["warning"] = (
                f"A card with this exact front already exists (id "
                f"{duplicate['id']}). Both cards were kept; consider "
                "editing one or making the fronts distinct."
            )
        return _ok(payload)
    except Exception as exc:  # never raise across the host boundary
        return _err(f"recall_add failed: {exc}")


# ----------------------------------------------------------------------
# recall_due
# ----------------------------------------------------------------------


def recall_due(args: dict, **kwargs) -> str:
    """List cards due now, oldest-due first."""
    try:
        args = args or {}
        limit = args.get("limit")
        store = get_store()
        today = _today()
        due = store.due_cards(today=today)
        total_due = len(due)
        if limit is not None:
            due = due[: max(0, int(limit))]
        return _ok(
            {
                "due_count": total_due,
                "showing": len(due),
                "cards": [_public_card(c) for c in due],
                "quiz_tip": (
                    "Ask one card at a time by its front. Do not show the "
                    "back until the user has answered from memory, then "
                    "grade with recall_grade."
                )
                if total_due
                else None,
            }
        )
    except Exception as exc:
        return _err(f"recall_due failed: {exc}")


# ----------------------------------------------------------------------
# recall_grade
# ----------------------------------------------------------------------


def recall_grade(args: dict, **kwargs) -> str:
    """Grade a card and reschedule it with SM-2.

    ``card_id`` is optional: without it, the earliest due card (the one
    a quiz would present first) is graded — that is the "current card".
    ``grade`` accepts again/hard/good/easy or a number 0-5.
    """
    try:
        args = args or {}
        if "grade" not in args:
            return _err(
                "recall_grade requires 'grade' (again/hard/good/easy or 0-5)."
            )
        try:
            quality = parse_grade(args.get("grade"))
        except ValueError as exc:
            return _err(str(exc))

        store = get_store()
        today = _today()
        card_id = args.get("card_id")
        if card_id is not None:
            card = store.get_card(int(card_id))
            if card is None:
                return _err(f"No card with id {card_id}.")
        else:
            due = store.due_cards(today=today, limit=1)
            if not due:
                return _err("No card is due right now, so there is no current card to grade.")
            card = due[0]

        new_state = apply_grade(card["state"], quality, today)
        store.record_review(card["id"], quality, new_state, today=today)

        remaining = store.due_cards(today=today, limit=1)
        return _ok(
            {
                "graded": {
                    "id": card["id"],
                    "front": card["front"],
                    "grade": grade_name(quality),
                    "quality": quality,
                    "new_interval_days": new_state.interval,
                    "next_due": new_state.due.isoformat() if new_state.due else None,
                    "ease": round(new_state.ease, 2),
                    "repetitions": new_state.repetitions,
                    "lapsed": quality < 3,
                },
                "remaining_due": len(store.due_cards(today=today)),
                "next_card": _public_card(remaining[0], with_back=False) if remaining else None,
            }
        )
    except Exception as exc:
        return _err(f"recall_grade failed: {exc}")


# ----------------------------------------------------------------------
# recall_stats
# ----------------------------------------------------------------------


def recall_stats(args: dict, **kwargs) -> str:
    """Counts, streak and retention across the whole deck."""
    try:
        store = get_store()
        today = _today()
        stats = store.review_stats(today=today)
        due = store.due_cards(today=today)
        retention = stats["retention"]
        return _ok(
            {
                "total_cards": store.count_cards(),
                "due_now": len(due),
                "next_due": store.next_due_date(today=today),
                "total_reviews": stats["total_reviews"],
                "reviewed_today": stats["reviewed_today"],
                "retention": round(retention, 3) if retention is not None else None,
                "streak_days": stats["streak_days"],
            }
        )
    except Exception as exc:
        return _err(f"recall_stats failed: {exc}")


#: Tool name -> handler, used by __init__.register and the tests.
HANDLERS = {
    "recall_add": recall_add,
    "recall_grade": recall_grade,
    "recall_due": recall_due,
    "recall_stats": recall_stats,
}
