"""The one place lesson-type codes are defined.

Ingest publishes this mapping in index.json so the frontend uses the same codes.
"""

LESSON_TYPE_CODES = {
    "Lecture": "LEC",
}

INCLUDED_LESSON_TYPES = frozenset({"Lecture"})
