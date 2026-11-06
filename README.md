# Recall — spaced repetition inside Hermes Agent

Your agent remembers everything. **Recall makes sure *you* do too.**

Anything worth remembering — the `git` incantation you always look up,
the API quirk that bit you last month, a word in the language you're
learning, a fact from a paper — becomes a flashcard with one tool call.
Recall schedules every card with the **SM-2 spaced-repetition
algorithm** (the one behind SuperMemo and Anki): review at 1 day, then
6 days, then at exponentially growing intervals that adapt to how well
*you* recall each card. When cards come due, Hermes opens your session
with a 60-second quiz — it asks, you answer from memory, you self-grade,
and the schedule adapts.

A prompt can tell an agent to quiz you. It cannot keep per-card SM-2
state across sessions, know what's due *today*, or track your streak.
Recall can, because it's real machinery: four tools, two lifecycle
hooks, a slash command, and a local SQLite store.

## Tools

| Tool | What it does |
| --- | --- |
| `recall_add` | Create a card (`front`, `back`, optional `deck` / `tags`). New cards are due immediately. Warns on exact-duplicate fronts. |
| `recall_due` | List cards due now, oldest-due first. |
| `recall_grade` | Grade the current card — `again` / `hard` / `good` / `easy` (or 0–5) — and reschedule it with SM-2. |
| `recall_stats` | Total cards, due count, next due date, streak, and retention. |

Plus the **`/recall`** slash command (summary; `/recall due` lists the
next due fronts) and a bundled **card-hygiene skill** that teaches the
agent to write atomic cards with exact answers and no duplicates.

## Install

Via the Hermes plugin catalog (once listed):

```
hermes plugins install recall
hermes plugins enable recall
```

From source:

```
git clone <this-repo> ~/.hermes/plugins/recall
hermes plugins enable recall
```

Requires Hermes Agent `>=0.21.5`. Recall itself has **zero Python
dependencies** (standard library only), needs **no network access, no
accounts, and no credentials**.

## Usage

Just talk:

> **You:** remember: `git rebase -i HEAD~3` — interactively rebase the last 3 commits
> **Hermes:** *(calls `recall_add`)* Card created — it'll be in your first quiz.

Next session, with the card due:

> **Hermes:** Quick Recall check before we start — 1 card due: *What does `git rebase -i HEAD~3` do?*
> **You:** Lets me edit/squash the last 3 commits interactively.
> **Hermes:** Back says: "interactively rebase the last 3 commits". Grade yourself?
> **You:** good
> **Hermes:** *(calls `recall_grade`)* Done — next review in 6 days.

And `/recall` any time:

```
Recall: 3 due now · 42 cards total · streak 9d · retention 87% · 5 reviewed today
Next due: 2026-11-09
```

## The demo loop

1. Add 3 cards in chat (commands you keep forgetting work great).
2. `/recall` — see them queued as due.
3. Start a new session: Hermes offers the quiz *unprompted*, because
   the cards are due.
4. Answer, grade one `hard` and one `easy`, and watch the intervals
   move differently (hard → short, easy → long).

## What Recall does to your sessions (honest disclosure)

Catalog rules ask for risky behaviour up front; Recall has exactly one
behaviour worth disclosing, and no others:

- **One context note, at most once per session.** Recall registers a
  `pre_llm_call` hook. On the first turn of a session *in which cards
  are due*, it appends a short note to that turn telling the agent how
  many cards are due (previewing up to 3 fronts, configurable via the
  `quiz_size` setting) and inviting it to offer a quick review. If
  nothing is due, **nothing is injected**. If you decline the quiz, the
  note instructs the agent to drop it and not mention it again that
  session. The hook never blocks a turn, and any internal error makes
  it silently do nothing.
- **Local storage only.** Cards, review history and session-activity
  days live in a SQLite database in Hermes' plugin-data directory
  (`plugin_db("recall")` → `<HERMES_HOME>/plugin-data/recall/data.db`).
  It survives plugin updates and removal. Nothing is written anywhere
  else.
- **No network, no telemetry, no credentials, no shell commands, no
  background processes, no self-updating code.** The catalog pin is the
  code you run; updates arrive only as new reviewed pins.

Settings (`plugins.entries.recall.settings`):

| Key | Default | Meaning |
| --- | --- | --- |
| `quiz_size` | `3` | How many due-card fronts the session note previews (1–10). |

## How it works

SM-2, per card: an **ease factor** (starts 2.5, floored at 1.3), a
**repetition** count of consecutive successful recalls, and an
**interval**. Grades ≥ 3 (of 0–5) are successes: intervals go 1 day →
6 days → `round(interval × ease)`. A grade below 3 is a lapse:
repetitions reset and the card returns tomorrow. Ease adjusts after
every grade by the classic SM-2 formula. All scheduling is
deterministic and offline.

Development helpers: `RECALL_TODAY=YYYY-MM-DD` fast-forwards "today"
(demo/tests), `RECALL_DB_PATH` points the store at a throwaway file.
Run the unit tests with:

```
python3 -I tests/test_recall.py
```

## License

MIT
