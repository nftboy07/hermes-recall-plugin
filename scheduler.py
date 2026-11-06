"""SM-2 spaced-repetition scheduling — pure logic, no I/O, no host imports.

Implements the classic SM-2 algorithm (Wozniak) as popularised by SuperMemo
and Anki:

- Each card carries an ease factor (EF, starts at 2.5, floored at 1.3),
  a repetition count (consecutive successful recalls) and an interval in
  days.
- A grade is a quality score 0..5. Grades >= 3 count as a successful
  recall; grades < 3 are a lapse: repetitions reset to 0 and the card
  becomes due again in 1 day.
- Interval progression for successful recalls: 1 day, then 6 days, then
  ``round(previous_interval * ease)``.
- Ease update after every grade:
  ``EF' = EF + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))``, floored at 1.3.

Named-button grades map onto the quality scale as:
``again -> 1``, ``hard -> 3``, ``good -> 4``, ``easy -> 5``.

Everything here is deterministic: callers pass the current date in, so the
whole module is unit-testable offline.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, replace

#: SM-2 ease-factor floor. Below this, intervals stop shrinking usefully and
#: cards become "leeches"; the algorithm never lets EF drop under 1.3.
MIN_EASE = 1.3

#: Ease factor assigned to a brand-new card.
INITIAL_EASE = 2.5

#: Interval (days) after the first successful recall.
FIRST_INTERVAL = 1

#: Interval (days) after the second successful recall.
SECOND_INTERVAL = 6

#: Interval (days) a lapsed card waits before it is due again.
LAPSE_INTERVAL = 1

#: Named grades accepted by the tools, mapped to SM-2 quality scores.
GRADE_NAMES = {
    "again": 1,
    "hard": 3,
    "good": 4,
    "easy": 5,
}


@dataclass(frozen=True)
class CardState:
    """The scheduling-relevant state of one card."""

    ease: float = INITIAL_EASE
    interval: int = 0  # days; 0 means "never scheduled yet"
    repetitions: int = 0  # consecutive successful recalls
    due: _dt.date | None = None  # None means "due immediately" (new card)


def parse_grade(value) -> int:
    """Normalise a user/agent grade into an SM-2 quality int in 0..5.

    Accepts an int 0-5, a numeric string ("4"), or a named grade
    ("again"/"hard"/"good"/"easy", case-insensitive). Raises ValueError
    for anything else — callers in tools.py convert that into a JSON
    error result, never an exception across the host boundary.
    """
    if isinstance(value, bool):  # bool is an int subclass; reject explicitly
        raise ValueError(f"invalid grade: {value!r}")
    if isinstance(value, int):
        quality = value
    elif isinstance(value, float) and value.is_integer():
        quality = int(value)
    elif isinstance(value, str):
        text = value.strip().lower()
        if text in GRADE_NAMES:
            quality = GRADE_NAMES[text]
        else:
            try:
                quality = int(text)
            except ValueError:
                raise ValueError(f"invalid grade: {value!r}") from None
    else:
        raise ValueError(f"invalid grade: {value!r}")
    if not 0 <= quality <= 5:
        raise ValueError(f"grade out of range 0..5: {quality}")
    return quality


def grade_name(quality: int) -> str:
    """Best named label for a quality score (for human-facing output)."""
    if quality <= 1:
        return "again"
    if quality == 2:
        return "barely"
    if quality == 3:
        return "hard"
    if quality == 4:
        return "good"
    return "easy"


def apply_grade(state: CardState, quality: int, today: _dt.date) -> CardState:
    """Return the next scheduling state for ``state`` graded ``quality``.

    ``today`` is the date the review happened; the new due date is
    ``today + interval`` days.
    """
    if not 0 <= quality <= 5:
        raise ValueError(f"grade out of range 0..5: {quality}")

    # SM-2 ease update, applied on every grade and floored at MIN_EASE.
    delta = 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
    new_ease = max(MIN_EASE, state.ease + delta)

    if quality < 3:
        # Lapse: forget the streak, see the card again tomorrow.
        return replace(
            state,
            ease=new_ease,
            interval=LAPSE_INTERVAL,
            repetitions=0,
            due=today + _dt.timedelta(days=LAPSE_INTERVAL),
        )

    if state.repetitions == 0:
        new_interval = FIRST_INTERVAL
    elif state.repetitions == 1:
        new_interval = SECOND_INTERVAL
    else:
        new_interval = max(1, round(state.interval * new_ease))

    return replace(
        state,
        ease=new_ease,
        interval=new_interval,
        repetitions=state.repetitions + 1,
        due=today + _dt.timedelta(days=new_interval),
    )
