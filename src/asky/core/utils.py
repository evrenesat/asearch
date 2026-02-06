"""Utility functions and constants for asky core."""

import re
from typing import Set

# Common stopwords to filter from session names and slugs
STOPWORDS: Set[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "shall",
        "can",
        "need",
        "dare",
        "ought",
        "used",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "under",
        "again",
        "further",
        "then",
        "once",
        "here",
        "there",
        "when",
        "where",
        "why",
        "how",
        "all",
        "each",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "just",
        "also",
        "now",
        "what",
        "which",
        "who",
        "whom",
        "this",
        "that",
        "these",
        "those",
        "am",
        "and",
        "but",
        "if",
        "or",
        "because",
        "while",
        "although",
        "i",
        "me",
        "my",
        "myself",
        "we",
        "our",
        "ours",
        "ours",
        "ourselves",
        "you",
        "your",
        "yours",
        "yourself",
        "yourselves",
        "he",
        "him",
        "his",
        "himself",
        "she",
        "her",
        "hers",
        "herself",
        "it",
        "its",
        "itself",
        "they",
        "them",
        "their",
        "theirs",
        "themselves",
        "about",
        "tell",
        "no",
    }
)


def generate_slug(text: str, max_words: int = 5) -> str:
    """Generate a slug from text by extracting key words.

    Filters stopwords and joins with underscores.
    Example: "what is the meaning of life" -> "meaning_life"
    """
    if not text:
        return "untitled"

    # Extract words (alphanumeric only)
    words = re.findall(r"[a-zA-Z]+", text.lower())

    # Filter stopwords and short words
    key_words = [w for w in words if w not in STOPWORDS and len(w) > 2]

    # Take first N words
    selected = key_words[:max_words]

    if not selected:
        # Fallback if all words are stopwords or text is weird
        safe_fallback = re.sub(r"[^a-z0-9]", "", text.lower()[:20])
        return safe_fallback if safe_fallback else "session"

    return "_".join(selected)
