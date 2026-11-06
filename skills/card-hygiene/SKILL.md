---
name: card-hygiene
description: How to write flashcards that actually stick — atomic cards, exact answers, no duplicates. Loaded by the Recall plugin; consult it whenever creating or reviewing cards with recall_add / recall_due / recall_grade.
---

# Card hygiene — writing flashcards that stick

Recall's scheduler (SM-2) only works if the cards themselves are good.
A badly written card gets graded "hard" forever and teaches nothing.
Follow these rules whenever you create cards, and gently suggest a
rewrite when a user's card breaks them.

## The rules

1. **One idea per card.** If the back contains "and" joining two facts,
   split it into two cards. Atomic cards fail cleanly; compound cards
   fail ambiguously ("I knew half of it") and poison the grades.
2. **Front = a question or a cue, never a statement to recognise.**
   "What does `git rebase -i HEAD~3` do?" beats "git rebase -i". The
   user must *produce* the answer from memory, not nod at it.
3. **Back = short and exact.** One line where possible. For commands,
   give the exact command; for facts, the exact fact. No paragraphs,
   no "see also" — extra text gives away answers and slows grading.
4. **No duplicates.** Before adding, check `recall_due` / the add
   result's duplicate warning. If a card on the same front exists,
   prefer improving its back to creating a twin — two cards asking the
   same thing in the same words double the review load for nothing.
   Near-duplicates with *different angles* ("what does X do" vs "when
   would you avoid X") are fine and even good.
5. **Make it personal.** Cards stick when they encode the user's own
   near-misses: the flag they always forget, the word they always
   confuse, the API quirk that bit them. When a session surfaces such a
   moment, offer to capture it as a card on the spot.
6. **Grade honestly.** Map the user's self-report faithfully:
   couldn't recall → `again`; recalled with real effort or a small
   error → `hard`; correct → `good`; instant and certain → `easy`.
   Inflated grades stretch intervals and the fact is gone when it
   matters; deflated grades waste reviews.

## Quiz conduct

- Ask **one card at a time**, front only. Never show the back (or hint
  at it) before the user answers.
- After the answer, reveal the back, let the user self-grade, then call
  `recall_grade`. Do not argue with a self-grade; suggest card edits
  instead when the card itself was the problem.
- Keep a quiz short: if more than ~10 cards are due, clear the oldest
  first and offer to stop — a finished short quiz beats an abandoned
  long one.
