"""SQLite persistence for Recall — stdlib ``sqlite3`` only.

The store keeps three tables:

- ``cards``: one row per flashcard with its SM-2 state (ease factor,
  interval, repetitions, due date) plus front/back text, deck and tags.
- ``reviews``: one row per graded review (date + quality). This is the
  raw material for streaks and retention in ``recall_stats``.
- ``activity``: one row per local date on which a session started
  (written by the ``on_session_start`` hook).

The store takes an explicit database path or an existing connection,
so it is fully testable offline; tools.py obtains the real connection
from Hermes' ``plugin_db()`` helper. Dates are stored as ISO ``YYYY-MM-DD`` strings, which sort
lexicographically in chronological order — that is what makes due
ordering a simple ``ORDER BY``.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from pathlib import Path

try:  # package import (inside Hermes) or top-level import (unit tests)
    from .scheduler import CardState
except ImportError:  # pragma: no cover - exercised by the test harness
    from scheduler import CardState

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    front       TEXT NOT NULL,
    back        TEXT NOT NULL,
    deck        TEXT NOT NULL DEFAULT 'default',
    tags        TEXT NOT NULL DEFAULT '',
    ease        REAL NOT NULL DEFAULT 2.5,
    interval    INTEGER NOT NULL DEFAULT 0,
    repetitions INTEGER NOT NULL DEFAULT 0,
    lapses      INTEGER NOT NULL DEFAULT 0,
    due_date    TEXT,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id     INTEGER NOT NULL REFERENCES cards(id),
    quality     INTEGER NOT NULL,
    reviewed_on TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activity (
    day         TEXT PRIMARY KEY
);
"""


def _date_str(day: _dt.date) -> str:
    return day.isoformat()


def _card_from_row(row: sqlite3.Row) -> dict:
    due = row["due_date"]
    return {
        "id": row["id"],
        "front": row["front"],
        "back": row["back"],
        "deck": row["deck"],
        "tags": [t for t in row["tags"].split(",") if t],
        "ease": row["ease"],
        "interval": row["interval"],
        "repetitions": row["repetitions"],
        "lapses": row["lapses"],
        "due_date": due,
        "created_at": row["created_at"],
        "state": CardState(
            ease=row["ease"],
            interval=row["interval"],
            repetitions=row["repetitions"],
            due=_dt.date.fromisoformat(due) if due else None,
        ),
    }


class Store:
    """A small, synchronous SQLite store for one Recall database.

    Construct with a filesystem path (tests, fallback) or with an
    existing ``sqlite3.Connection`` — inside Hermes, the connection
    comes from ``plugins.plugin_storage.plugin_db("recall")``, which
    opens ``<HERMES_HOME>/plugin-data/recall/data.db`` in WAL mode.
    """

    def __init__(self, db_path=None, connection=None):
        if connection is not None:
            self._conn = connection
            self._conn.row_factory = sqlite3.Row
        else:
            path = Path(db_path)
            if path.parent and str(path.parent) not in ("", "."):
                path.parent.mkdir(parents=True, exist_ok=True)
            # check_same_thread=False: hooks and tools may run on
            # different host threads; writes are short and serialised
            # by SQLite itself.
            self._conn = sqlite3.connect(str(path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # -- cards ---------------------------------------------------------

    def add_card(
        self,
        front: str,
        back: str,
        deck: str = "default",
        tags: list[str] | None = None,
        today: _dt.date | None = None,
    ) -> dict:
        """Insert a new card. New cards are due immediately."""
        today = today or _dt.date.today()
        cur = self._conn.execute(
            "INSERT INTO cards (front, back, deck, tags, ease, interval,"
            " repetitions, lapses, due_date, created_at)"
            " VALUES (?, ?, ?, ?, 2.5, 0, 0, 0, ?, ?)",
            (
                front,
                back,
                deck or "default",
                ",".join(tags or []),
                _date_str(today),
                _date_str(today),
            ),
        )
        self._conn.commit()
        return self.get_card(int(cur.lastrowid))

    def get_card(self, card_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM cards WHERE id = ?", (card_id,)
        ).fetchone()
        return _card_from_row(row) if row else None

    def find_card_by_front(self, front: str) -> dict | None:
        """Exact-match lookup used to warn about duplicate cards."""
        row = self._conn.execute(
            "SELECT * FROM cards WHERE front = ? ORDER BY id LIMIT 1",
            (front,),
        ).fetchone()
        return _card_from_row(row) if row else None

    def due_cards(self, today: _dt.date | None = None, limit: int | None = None) -> list[dict]:
        """Cards due on or before ``today``, oldest-due first.

        Cards whose due date is furthest in the past come first, so a
        backlog drains in the order the cards were originally scheduled.
        """
        today = today or _dt.date.today()
        sql = (
            "SELECT * FROM cards WHERE due_date IS NULL OR due_date <= ?"
            " ORDER BY COALESCE(due_date, '0000-01-01') ASC, id ASC"
        )
        params: list = [_date_str(today)]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = self._conn.execute(sql, params).fetchall()
        return [_card_from_row(r) for r in rows]

    def next_due_date(self, today: _dt.date | None = None) -> str | None:
        """The earliest future due date, or None if everything is due."""
        today = today or _dt.date.today()
        row = self._conn.execute(
            "SELECT MIN(due_date) AS d FROM cards WHERE due_date > ?",
            (_date_str(today),),
        ).fetchone()
        return row["d"] if row else None

    def count_cards(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM cards").fetchone()
        return int(row["n"])

    # -- reviews -------------------------------------------------------

    def record_review(
        self,
        card_id: int,
        quality: int,
        new_state: CardState,
        today: _dt.date | None = None,
    ) -> None:
        """Persist the outcome of grading one card."""
        today = today or _dt.date.today()
        lapsed = 1 if quality < 3 else 0
        self._conn.execute(
            "UPDATE cards SET ease = ?, interval = ?, repetitions = ?,"
            " lapses = lapses + ?, due_date = ? WHERE id = ?",
            (
                new_state.ease,
                new_state.interval,
                new_state.repetitions,
                lapsed,
                _date_str(new_state.due) if new_state.due else None,
                card_id,
            ),
        )
        self._conn.execute(
            "INSERT INTO reviews (card_id, quality, reviewed_on)"
            " VALUES (?, ?, ?)",
            (card_id, quality, _date_str(today)),
        )
        self._conn.commit()

    def review_stats(self, today: _dt.date | None = None) -> dict:
        """Aggregate review history: totals, retention and streak.

        Retention = share of all reviews graded >= 3 (successful recall).
        Streak = consecutive days with at least one review, counting back
        from today; a today with no reviews yet does not break the streak
        (yesterday's run still counts until today ends).
        """
        today = today or _dt.date.today()
        row = self._conn.execute(
            "SELECT COUNT(*) AS total,"
            " COALESCE(SUM(CASE WHEN quality >= 3 THEN 1 ELSE 0 END), 0)"
            " AS passed FROM reviews"
        ).fetchone()
        total = int(row["total"])
        passed = int(row["passed"])
        retention = (passed / total) if total else None

        reviewed_today = int(
            self._conn.execute(
                "SELECT COUNT(*) AS n FROM reviews WHERE reviewed_on = ?",
                (_date_str(today),),
            ).fetchone()["n"]
        )

        days = {
            r["reviewed_on"]
            for r in self._conn.execute(
                "SELECT DISTINCT reviewed_on FROM reviews"
            ).fetchall()
        }
        streak = 0
        cursor = today
        if _date_str(cursor) not in days:
            cursor = cursor - _dt.timedelta(days=1)
        while _date_str(cursor) in days:
            streak += 1
            cursor = cursor - _dt.timedelta(days=1)

        return {
            "total_reviews": total,
            "passed_reviews": passed,
            "retention": retention,
            "reviewed_today": reviewed_today,
            "streak_days": streak,
        }

    # -- activity ------------------------------------------------------

    def mark_active(self, today: _dt.date | None = None) -> None:
        """Record that a session started today (idempotent)."""
        today = today or _dt.date.today()
        self._conn.execute(
            "INSERT OR IGNORE INTO activity (day) VALUES (?)",
            (_date_str(today),),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
