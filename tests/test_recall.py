"""Unit tests for Recall's SM-2 scheduler, SQLite store, tool handlers,
hooks and slash command.

No Hermes host required. Run with:

    python3 -I tests/test_recall.py

Exits 0 and prints PASS when every check holds; raises AssertionError
(with the failing check's name) otherwise.
"""

import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scheduler  # noqa: E402
import store as store_mod  # noqa: E402
from scheduler import CardState, apply_grade, parse_grade  # noqa: E402

CHECKS = 0


def check(name, condition):
    global CHECKS
    CHECKS += 1
    if not condition:
        raise AssertionError(f"FAILED: {name}")


def approx(a, b, eps=1e-9):
    return abs(a - b) <= eps


D0 = dt.date(2026, 1, 5)  # a Monday; arbitrary fixed "today"
DAY = dt.timedelta(days=1)


# ----------------------------------------------------------------------
# Scheduler: grade parsing
# ----------------------------------------------------------------------

def test_parse_grade():
    check("name again", parse_grade("again") == 1)
    check("name hard", parse_grade("hard") == 3)
    check("name good", parse_grade("good") == 4)
    check("name easy", parse_grade("easy") == 5)
    check("name case/space", parse_grade("  Easy ") == 5)
    check("int", parse_grade(0) == 0 and parse_grade(5) == 5)
    check("numeric string", parse_grade("4") == 4)
    for bad in ("meh", 6, -1, None, True, 2.5):
        try:
            parse_grade(bad)
        except ValueError:
            check(f"rejects {bad!r}", True)
        else:
            check(f"rejects {bad!r}", False)


# ----------------------------------------------------------------------
# Scheduler: SM-2 math
# ----------------------------------------------------------------------

def test_interval_progression():
    s = CardState()  # ease 2.5, interval 0, reps 0, due None
    s = apply_grade(s, 4, D0)  # good
    check("first interval is 1", s.interval == 1 and s.repetitions == 1)
    check("first due is tomorrow", s.due == D0 + DAY)
    check("good keeps ease 2.5", approx(s.ease, 2.5))

    s = apply_grade(s, 4, D0 + DAY)  # good again
    check("second interval is 6", s.interval == 6 and s.repetitions == 2)
    check("second due", s.due == D0 + DAY + 6 * DAY)

    s = apply_grade(s, 4, D0 + 7 * DAY)  # good a third time
    check("third interval is round(6*2.5)=15", s.interval == 15)
    check("third due", s.due == D0 + 7 * DAY + 15 * DAY)

    s = apply_grade(s, 5, D0 + 22 * DAY)  # easy: ease rises to 2.6
    check("easy raises ease to 2.6", approx(s.ease, 2.6))
    check("fourth interval round(15*2.6)=39", s.interval == 39)


def test_ease_math():
    base = CardState(ease=2.5, interval=6, repetitions=2)
    # q=3: delta = 0.1 - 2*(0.08 + 2*0.02) = -0.14
    check("hard delta -0.14", approx(apply_grade(base, 3, D0).ease, 2.36))
    # q=5: delta = +0.1
    check("easy delta +0.10", approx(apply_grade(base, 5, D0).ease, 2.6))
    # q=0: delta = 0.1 - 5*(0.08 + 5*0.02) = -0.8
    check("zero delta -0.80", approx(apply_grade(base, 0, D0).ease, 1.7))


def test_ease_floor():
    s = CardState(ease=1.4, interval=30, repetitions=5)
    for _ in range(10):
        s = apply_grade(s, 0, D0)
        check("ease never below 1.3", s.ease >= scheduler.MIN_EASE)
    check("ease settles at floor", approx(s.ease, 1.3))


def test_lapse_reset():
    s = CardState(ease=2.5, interval=15, repetitions=3, due=D0)
    s2 = apply_grade(s, 1, D0)  # "again"
    check("lapse resets repetitions", s2.repetitions == 0)
    check("lapse interval is 1 day", s2.interval == 1)
    check("lapse due tomorrow", s2.due == D0 + DAY)
    # ease still updates: q=1 -> delta = 0.1 - 4*(0.08+4*0.02) = -0.54
    check("lapse ease 2.5-0.54", approx(s2.ease, 1.96))
    # and a success right after the lapse restarts the 1 -> 6 ladder
    s3 = apply_grade(s2, 4, D0 + DAY)
    check("post-lapse first interval 1", s3.interval == 1 and s3.repetitions == 1)


# ----------------------------------------------------------------------
# Store
# ----------------------------------------------------------------------

def make_store():
    tmp = tempfile.mkdtemp(prefix="recall-test-")
    return store_mod.Store(Path(tmp) / "data.db")


def test_store_add_and_get():
    st = make_store()
    card = st.add_card("What is 2+2?", "4", tags=["math"], today=D0)
    check("id assigned", card["id"] >= 1)
    check("new card due today", card["due_date"] == D0.isoformat())
    check("new card ease 2.5", approx(card["ease"], 2.5))
    again = st.get_card(card["id"])
    check("round trip front", again["front"] == "What is 2+2?")
    check("round trip tags", again["tags"] == ["math"])
    check("missing card is None", st.get_card(999999) is None)
    check("count", st.count_cards() == 1)
    dup = st.find_card_by_front("What is 2+2?")
    check("duplicate lookup", dup is not None and dup["id"] == card["id"])


def test_due_ordering():
    st = make_store()
    a = st.add_card("A", "a", today=D0 - 2 * DAY)  # due two days ago
    b = st.add_card("B", "b", today=D0)  # due today
    c = st.add_card("C", "c", today=D0 - DAY)  # due yesterday
    # Push C into the future by grading it "good" today.
    st.record_review(c["id"], 4, apply_grade(c["state"], 4, D0), today=D0)
    due = st.due_cards(today=D0)
    ids = [x["id"] for x in due]
    check("future card not due", c["id"] not in ids)
    check("oldest due first", ids == [a["id"], b["id"]])
    check("next due is C in 1 day", st.next_due_date(today=D0) == (D0 + DAY).isoformat())
    due_tomorrow = st.due_cards(today=D0 + DAY)
    check("C due tomorrow", [x["id"] for x in due_tomorrow][-1] == c["id"])


def test_review_stats_and_streak():
    st = make_store()
    card = st.add_card("Q", "A", today=D0)
    state = card["state"]
    # Jan 3: good; Jan 4: again (lapse); Jan 5 (today): easy
    for day, q in ((D0 - 2 * DAY, 4), (D0 - DAY, 1), (D0, 5)):
        state = apply_grade(state, q, day)
        st.record_review(card["id"], q, state, today=day)
    stats = st.review_stats(today=D0)
    check("total reviews 3", stats["total_reviews"] == 3)
    check("passed 2", stats["passed_reviews"] == 2)
    check("retention 2/3", approx(stats["retention"], 2 / 3))
    check("reviewed today 1", stats["reviewed_today"] == 1)
    check("streak 3 days", stats["streak_days"] == 3)
    # The lapse was recorded on the card.
    after = st.get_card(card["id"])
    check("lapse counted", after["lapses"] == 1)

    # Streak semantics: no review yet today -> yesterday's run still counts.
    st2 = make_store()
    c2 = st2.add_card("Q2", "A2", today=D0 - 2 * DAY)
    s2state = c2["state"]
    for day in (D0 - 2 * DAY, D0 - DAY):
        s2state = apply_grade(s2state, 4, day)
        st2.record_review(c2["id"], 4, s2state, today=day)
    check(
        "streak survives a not-yet-reviewed today",
        st2.review_stats(today=D0)["streak_days"] == 2,
    )
    check(
        "streak broken after a skipped day",
        st2.review_stats(today=D0 + 2 * DAY)["streak_days"] == 0,
    )


def test_store_connection_mode():
    # Inside Hermes the store wraps the connection plugin_db() returns.
    import sqlite3

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    st = store_mod.Store(connection=conn)
    card = st.add_card("CQ", "CA", today=D0)
    check("connection mode add/get", st.get_card(card["id"])["front"] == "CQ")
    check("connection mode due", len(st.due_cards(today=D0)) == 1)


def test_activity():
    st = make_store()
    st.mark_active(today=D0)
    st.mark_active(today=D0)  # idempotent
    st.mark_active(today=D0 + DAY)
    rows = st._conn.execute("SELECT COUNT(*) AS n FROM activity").fetchone()
    check("activity days recorded once each", rows["n"] == 2)


# ----------------------------------------------------------------------
# Tool handlers (with RECALL_DB_PATH / RECALL_TODAY overrides)
# ----------------------------------------------------------------------

def fresh_tools(day):
    tmp = tempfile.mkdtemp(prefix="recall-tools-")
    os.environ["RECALL_DB_PATH"] = str(Path(tmp) / "data.db")
    os.environ["RECALL_TODAY"] = day.isoformat()
    import tools

    tools._STORE = None  # force reopen against the new path
    return tools


def test_tools_end_to_end():
    import hooks
    import commands

    tools = fresh_tools(D0)
    out = json.loads(tools.recall_add({"front": "cmd?", "back": "cmd!"}))
    check("add ok", out["ok"] and out["card"]["front"] == "cmd?")
    out = json.loads(tools.recall_add({"front": "", "back": "x"}))
    check("add rejects empty front", not out["ok"])
    out = json.loads(tools.recall_add({"front": "cmd?", "back": "again"}))
    check("duplicate warning", out["ok"] and "warning" in out)

    due = json.loads(tools.recall_due({}))
    check("two cards due", due["due_count"] == 2)

    # Grade the current (earliest due) card "good" with no card_id.
    g = json.loads(tools.recall_grade({"grade": "good"}))
    check("grade ok", g["ok"] and g["graded"]["new_interval_days"] == 1)
    check("one remaining", g["remaining_due"] == 1)
    g2 = json.loads(tools.recall_grade({"grade": 5, "card_id": g["next_card"]["id"]}))
    check("grade by id ok", g2["ok"] and g2["remaining_due"] == 0)
    g3 = json.loads(tools.recall_grade({"grade": "good"}))
    check("grade with nothing due errors cleanly", not g3["ok"])
    g4 = json.loads(tools.recall_grade({"grade": "banana"}))
    check("bad grade errors cleanly", not g4["ok"])

    # Next day: both cards are due again (interval was 1).
    os.environ["RECALL_TODAY"] = (D0 + DAY).isoformat()
    due2 = json.loads(tools.recall_due({}))
    check("cards due next day", due2["due_count"] == 2)
    stats = json.loads(tools.recall_stats({}))
    check("stats total", stats["total_cards"] == 2)
    check("stats reviews", stats["total_reviews"] == 2)
    check("stats retention 1.0", approx(stats["retention"], 1.0))
    check("stats streak 1 (yesterday only)", stats["streak_days"] == 1)

    # Hook: injects once per session, only when something is due.
    hooks._NOTED_SESSIONS.clear()
    note = hooks.pre_llm_call(session_id="s1", user_message="hi")
    check("hook injects when due", isinstance(note, dict) and "2 flashcard" in note["context"])
    again = hooks.pre_llm_call(session_id="s1", user_message="hi again")
    check("hook injects at most once per session", again is None)
    other = hooks.pre_llm_call(session_id="s2", user_message="hi")
    check("hook injects for a new session", isinstance(other, dict))

    # Grade everything away, then the hook must stay silent.
    json.loads(tools.recall_grade({"grade": "easy"}))
    json.loads(tools.recall_grade({"grade": "easy"}))
    hooks._NOTED_SESSIONS.clear()
    silent = hooks.pre_llm_call(session_id="s3", user_message="hi")
    check("hook silent when nothing due", silent is None)

    # Slash command.
    text = commands.recall_command("")
    check("command shows due count", "due now" in text)
    empty = fresh_tools(D0)
    _ = empty  # separate store already covered by count check below
    check("command never raises", isinstance(commands.recall_command("due"), str))


def test_command_empty_deck():
    import commands

    fresh_tools(D0)  # brand-new empty database
    text = commands.recall_command("")
    check("empty deck message", "no cards yet" in text.lower())


# ----------------------------------------------------------------------

def main():
    test_parse_grade()
    test_interval_progression()
    test_ease_math()
    test_ease_floor()
    test_lapse_reset()
    test_store_add_and_get()
    test_due_ordering()
    test_review_stats_and_streak()
    test_store_connection_mode()
    test_activity()
    test_tools_end_to_end()
    test_command_empty_deck()
    print(f"PASS — {CHECKS} checks")


if __name__ == "__main__":
    main()
