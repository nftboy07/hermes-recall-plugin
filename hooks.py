"""Recall lifecycle hooks.

Two hooks, both designed to be invisible when there is nothing to do:

- ``on_session_start`` stamps the day in the activity table (used for
  streak bookkeeping). It is a pure observer and returns nothing.
- ``pre_llm_call`` is the polite nudge: if cards are due, it injects a
  short context note into the current turn so the agent can offer a
  quick review. The discipline is strict:

  * **Nothing due → no injection at all** (returns None).
  * **At most once per session** — sessions that already got the note
    are remembered in a module-level set; the note never repeats.
  * **Never blocks** — it never returns a block action, and any internal
    error is swallowed (returns None) so a Recall bug can never break
    or delay a user's turn.

Disclosure: this hook is the plugin's only behaviour that affects turns
the user did not explicitly start with Recall, and it is documented in
the README under "What Recall does to your sessions".
"""

from __future__ import annotations

try:  # package import (inside Hermes) or top-level import (unit tests)
    from . import tools as _tools
except ImportError:  # pragma: no cover - exercised by the test harness
    import tools as _tools

# Sessions (by session_id) that already received the due-cards note in
# this process. In-memory on purpose: the note is a per-session courtesy,
# not durable state, and a host restart simply re-arms it.
_NOTED_SESSIONS: set[str] = set()

# How many card fronts the note may preview. Set from plugin config in
# register(); the default matches the manifest's config_schema default.
QUIZ_SIZE = 3


def set_quiz_size(value) -> None:
    """Configure the preview size (called once from register())."""
    global QUIZ_SIZE
    try:
        size = int(value)
    except (TypeError, ValueError):
        return
    if 1 <= size <= 10:
        QUIZ_SIZE = size


def on_session_start(session_id=None, platform=None, **kwargs):
    """Stamp today's activity. Observer only; never returns a value."""
    try:
        _tools.get_store().mark_active(today=_tools._today())
    except Exception:
        pass
    return None


def pre_llm_call(
    session_id=None,
    user_message=None,
    conversation_history=None,
    is_first_turn=False,
    model=None,
    platform=None,
    **kwargs,
):
    """Inject a short "cards are due" note, at most once per session."""
    try:
        key = session_id or ""
        if key and key in _NOTED_SESSIONS:
            return None

        store = _tools.get_store()
        today = _tools._today()
        due = store.due_cards(today=today)
        if not due:
            return None

        if key:
            _NOTED_SESSIONS.add(key)

        fronts = [c["front"] for c in due[:QUIZ_SIZE]]
        preview = "; ".join(fronts)
        if len(due) > len(fronts):
            preview += f"; … and {len(due) - len(fronts)} more"
        note = (
            f"[Recall] The user has {len(due)} flashcard(s) due for "
            f"spaced-repetition review today ({preview}). If it fits the "
            "moment, briefly offer a quick review before or after the "
            "main task: ask one card's front at a time, wait for the "
            "user's answer, then grade it with recall_grade. If the user "
            "declines or is busy, drop it without insisting — do not "
            "mention this note again this session."
        )
        return {"context": note}
    except Exception:
        # A Recall failure must never break or block the user's turn.
        return None
