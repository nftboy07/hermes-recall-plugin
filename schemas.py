"""JSON schemas describing Recall's tools to the model.

One dict per tool, in the shape ``ctx.register_tool`` expects: a
``name``, a human/model-facing ``description``, and a JSON-Schema
``parameters`` object. Kept free of any host imports so it can be
validated (and unit-tested) standalone.
"""

RECALL_ADD = {
    "name": "recall_add",
    "description": (
        "Create a flashcard for spaced-repetition review. Use this when "
        "the user wants to remember something durable: a command, a "
        "fact, a word, an API quirk. Keep cards atomic — one idea per "
        "card, front phrased as a question or prompt, back short and "
        "exact. New cards are due immediately."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "front": {
                "type": "string",
                "description": "The prompt side of the card (a question or cue).",
            },
            "back": {
                "type": "string",
                "description": "The answer side of the card (short and exact).",
            },
            "deck": {
                "type": "string",
                "description": "Optional deck name to file the card under (default: 'default').",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of short tags.",
            },
        },
        "required": ["front", "back"],
    },
}

RECALL_DUE = {
    "name": "recall_due",
    "description": (
        "List flashcards that are due for review right now, oldest-due "
        "first. Each card includes its back (the answer) — when quizzing "
        "the user, present only the front, wait for their answer, and "
        "reveal the back only afterwards."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Optional maximum number of cards to return.",
                "minimum": 1,
            }
        },
        "required": [],
    },
}

RECALL_GRADE = {
    "name": "recall_grade",
    "description": (
        "Grade the card the user just answered and reschedule it with "
        "the SM-2 algorithm. Grade honestly from the user's self-report: "
        "'again' = could not recall, 'hard' = recalled with effort, "
        "'good' = recalled correctly, 'easy' = recalled instantly. A "
        "numeric quality 0-5 is also accepted. If card_id is omitted, "
        "the earliest due card (the current quiz card) is graded."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "grade": {
                "type": "string",
                "description": "One of: again, hard, good, easy — or a number 0-5.",
            },
            "card_id": {
                "type": "integer",
                "description": "Optional id of the card to grade (from recall_due).",
            },
        },
        "required": ["grade"],
    },
}

RECALL_STATS = {
    "name": "recall_stats",
    "description": (
        "Get Recall statistics: total cards, cards due now, the next "
        "due date, total reviews, reviews today, retention (share of "
        "reviews recalled successfully) and the current daily streak."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

#: Tool name -> schema, in registration order.
SCHEMAS = {
    "recall_add": RECALL_ADD,
    "recall_grade": RECALL_GRADE,
    "recall_due": RECALL_DUE,
    "recall_stats": RECALL_STATS,
}

#: The toolset all Recall tools are registered under.
TOOLSET = "recall"
