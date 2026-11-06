"""Recall — spaced repetition inside Hermes Agent.

``register(ctx)`` is the plugin entry point, called exactly once at
startup. It wires up everything the manifest declares:

- four tools (``recall_add``, ``recall_grade``, ``recall_due``,
  ``recall_stats``) under the ``recall`` toolset,
- two hooks (``pre_llm_call`` — the once-per-session due-cards note;
  ``on_session_start`` — activity stamp),
- the ``/recall`` slash command,
- one bundled skill (``card-hygiene``).

No network, no credentials, no dependencies: scheduling state lives in
the plugin's own SQLite database via Hermes' ``plugin_db()`` helper.
"""

from __future__ import annotations

from pathlib import Path

try:  # package import (inside Hermes)
    from . import commands, hooks
    from .schemas import SCHEMAS, TOOLSET
    from .tools import HANDLERS
except ImportError:  # pragma: no cover - direct module import fallback
    import commands
    import hooks
    from schemas import SCHEMAS, TOOLSET
    from tools import HANDLERS

_SKILL_NAME = "card-hygiene"
_SKILL_FILE = Path(__file__).parent / "skills" / _SKILL_NAME / "SKILL.md"


def register(ctx) -> None:
    # Tools -------------------------------------------------------------
    for name, schema in SCHEMAS.items():
        ctx.register_tool(name, TOOLSET, schema, HANDLERS[name])

    # Hooks -------------------------------------------------------------
    ctx.register_hook("pre_llm_call", hooks.pre_llm_call)
    ctx.register_hook("on_session_start", hooks.on_session_start)

    # Slash command ------------------------------------------------------
    ctx.register_command(
        "recall",
        commands.recall_command,
        "Recall status: due count, next due, streak and retention "
        "('/recall due' also lists the next due cards).",
    )

    # Bundled skill -------------------------------------------------------
    ctx.register_skill(_SKILL_NAME, _SKILL_FILE)

    # Settings ------------------------------------------------------------
    # Optional: quiz_size from the plugin's config namespace
    # (plugins.entries.recall.settings). Any failure leaves the default.
    try:
        hooks.set_quiz_size(ctx.get_config("quiz_size", hooks.QUIZ_SIZE))
    except Exception:
        pass
