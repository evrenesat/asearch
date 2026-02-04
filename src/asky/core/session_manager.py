"""Session management logic for asky."""

import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from asky.config import (
    SESSION_COMPACTION_THRESHOLD,
    SESSION_COMPACTION_STRATEGY,
    SUMMARIZE_SESSION_PROMPT,
    MODELS,
    DEFAULT_CONTEXT_SIZE,
    SUMMARIZATION_MODEL,
)
from asky.storage import Session
from asky.storage.sqlite import SQLiteHistoryRepository
from asky.core.api_client import count_tokens, get_llm_msg, UsageTracker
from asky.summarization import _summarize_content
from asky.html import strip_think_tags

logger = logging.getLogger(__name__)

# Lock file for shell-sticky sessions
# Each terminal (identified by parent shell PID) gets its own lock file.
LOCK_DIR = Path("/tmp")
LOCK_PREFIX = "asky_session_"

# Common stopwords to filter from session names
STOPWORDS = frozenset(
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
    }
)


def generate_session_name(query: str, max_words: int = 2) -> str:
    """Generate a session name from query by extracting key words.

    Filters stopwords and joins with underscores.
    Example: "what is the meaning of life" -> "meaning_life"
    """
    # Extract words (alphanumeric only)
    words = re.findall(r"[a-zA-Z]+", query.lower())

    # Filter stopwords and short words
    key_words = [w for w in words if w not in STOPWORDS and len(w) > 2]

    # Take first N words
    selected = key_words[:max_words]

    if not selected:
        # Fallback if all words are stopwords
        return "session"

    return "_".join(selected)


def _get_shell_pid() -> int:
    """Get the parent shell's process ID."""
    return os.getppid()


def _get_lock_file_path() -> Path:
    """Return the lock file path for the current shell."""
    return LOCK_DIR / f"{LOCK_PREFIX}{_get_shell_pid()}"


def get_shell_session_id() -> Optional[int]:
    """Read the session ID from the shell's lock file, if any."""
    lock_file = _get_lock_file_path()
    if lock_file.exists():
        try:
            return int(lock_file.read_text().strip())
        except ValueError:
            return None
    return None


def set_shell_session_id(session_id: int) -> None:
    """Write the session ID to the shell's lock file."""
    lock_file = _get_lock_file_path()
    lock_file.write_text(str(session_id))
    logger.info(f"Session lock file created: {lock_file}")


def clear_shell_session() -> None:
    """Remove the shell's session lock file (detach from session)."""
    lock_file = _get_lock_file_path()
    if lock_file.exists():
        lock_file.unlink()
        logger.info(f"Session lock file removed: {lock_file}")


class DuplicateSessionError(Exception):
    """Raised when multiple sessions match a name and user must choose."""

    def __init__(self, name: str, sessions: List[Tuple[int, str, str]]):
        self.name = name
        self.sessions = sessions  # List of (id, name, preview)
        super().__init__(f"Multiple sessions named '{name}'")


class SessionManager:
    """Orchestrates persistent conversation sessions and compaction.

    Sessions are persistent conversation threads that never end.
    A shell attaches to a session via lock file, not DB state.
    """

    def __init__(
        self,
        model_config: Dict[str, Any],
        usage_tracker: Optional[UsageTracker] = None,
    ):
        self.repo = SQLiteHistoryRepository()
        self.model_config = model_config
        self.usage_tracker = usage_tracker
        self.current_session: Optional[Session] = None
        self.context_size = model_config.get("context_size", DEFAULT_CONTEXT_SIZE)

    def start_or_resume(
        self, session_name: Optional[str] = None, query: Optional[str] = None
    ) -> Session:
        """Start a new session or resume an existing one.

        Args:
            session_name: Name or ID to resume. If numeric, treated as ID.
            query: Query text for auto-generating session name if creating new.

        Returns:
            The session object.

        Raises:
            DuplicateSessionError: If multiple sessions match the name.
        """
        # Case 1: Resume by explicit ID (numeric session_name)
        if session_name and session_name.isdigit():
            session_id = int(session_name)
            session = self.repo.get_session_by_id(session_id)
            if session:
                self.current_session = session
                return session
            else:
                # ID not found, create new with this as name
                pass

        # Case 2: Resume by name (including S-prefixed IDs for backwards compat)
        if session_name:
            # Handle legacy S prefix
            if session_name.lower().startswith("s") and session_name[1:].isdigit():
                session_id = int(session_name[1:])
                session = self.repo.get_session_by_id(session_id)
                if session:
                    self.current_session = session
                    return session

            # Look up by name
            matching_sessions = self.repo.get_sessions_by_name(session_name)

            if len(matching_sessions) == 1:
                # Exact match, resume it
                self.current_session = matching_sessions[0]
                return self.current_session
            elif len(matching_sessions) > 1:
                # Multiple matches - raise error with details for user
                session_info = []
                for s in matching_sessions:
                    preview = self.repo.get_first_message_preview(s.id)
                    session_info.append((s.id, s.name, preview))
                raise DuplicateSessionError(session_name, session_info)
            else:
                # No match - create new with this name
                sid = self.repo.create_session(
                    self.model_config["alias"], name=session_name
                )
                self.current_session = self.repo.get_session_by_id(sid)
                return self.current_session

        # Case 3: No name provided - check shell lock file first
        shell_session_id = get_shell_session_id()
        if shell_session_id:
            session = self.repo.get_session_by_id(shell_session_id)
            if session:
                self.current_session = session
                return session
            # Lock file points to deleted session, clear it
            clear_shell_session()

        # Case 4: Create new session with auto-generated name
        auto_name = generate_session_name(query) if query else None
        sid = self.repo.create_session(self.model_config["alias"], name=auto_name)
        self.current_session = self.repo.get_session_by_id(sid)
        return self.current_session

    def build_context_messages(self) -> List[Dict[str, str]]:
        """Retrieve session messages and format them for context."""
        if not self.current_session:
            return []

        messages = []

        # 1. Add compacted summary if it exists
        if self.current_session.compacted_summary:
            messages.append(
                {
                    "role": "user",
                    "content": f"Previous conversation summary:\n{self.current_session.compacted_summary}",
                }
            )
            messages.append(
                {
                    "role": "assistant",
                    "content": "I understand the context. How can I help further?",
                }
            )

        # 2. Add recent messages (all messages after compaction for now)
        # In a more advanced version, we might only add messages AFTER the compaction timestamp.
        session_msgs = self.repo.get_session_messages(self.current_session.id)
        for msg in session_msgs:
            messages.append({"role": msg.role, "content": msg.content})

        return messages

    def save_turn(
        self, query: str, answer: str, query_summary: str = "", answer_summary: str = ""
    ) -> None:
        """Save a conversation turn to the session."""
        if not self.current_session:
            return

        # Calculate tokens (naive for now, improved later if needed)
        q_tokens = count_tokens([{"role": "user", "content": query}])
        a_tokens = count_tokens([{"role": "assistant", "content": answer}])

        self.repo.save_message(
            self.current_session.id, "user", query, query_summary, q_tokens
        )
        self.repo.save_message(
            self.current_session.id, "assistant", answer, answer_summary, a_tokens
        )

    def check_and_compact(self) -> bool:
        """Check if compaction is needed and trigger it."""
        if not self.current_session:
            return False

        # Calculate current session tokens
        messages = self.build_context_messages()
        current_token_count = count_tokens(messages)

        threshold_tokens = int(self.context_size * (SESSION_COMPACTION_THRESHOLD / 100))

        if current_token_count >= threshold_tokens:
            logger.info(
                f"Session {self.current_session.id} reached threshold ({current_token_count}/{threshold_tokens}). Compacting..."
            )
            return self._perform_compaction()

        return False

    def _perform_compaction(self) -> bool:
        """Perform compaction using the configured strategy."""
        if SESSION_COMPACTION_STRATEGY == "llm_summary":
            return self._compact_with_llm()
        else:
            return self._compact_with_summaries()

    def _compact_with_summaries(self) -> bool:
        """Concatenate existing summaries."""
        session_msgs = self.repo.get_session_messages(self.current_session.id)
        logger.info(
            f"Found {len(session_msgs)} messages to compact for session {self.current_session.id}"
        )
        summary_parts = []
        for msg in session_msgs:
            if msg.summary:
                summary_parts.append(f"{msg.role.capitalize()}: {msg.summary}")
            else:
                # Fallback to truncated content if no summary
                summary_parts.append(f"{msg.role.capitalize()}: {msg.content[:100]}...")

        compacted_content = "\n".join(summary_parts)
        logger.info(f"Compacted content length: {len(compacted_content)} chars")
        self.repo.compact_session(self.current_session.id, compacted_content)
        logger.info(f"Compaction saved for session {self.current_session.id}")
        return True

    def _compact_with_llm(self) -> bool:
        """Ask the model to summarize the whole session."""
        session_msgs = self.repo.get_session_messages(self.current_session.id)
        full_text = []
        for msg in session_msgs:
            full_text.append(f"{msg.role.capitalize()}: {msg.content}")

        conversation_blob = "\n\n".join(full_text)

        compacted_content = _summarize_content(
            content=conversation_blob,
            prompt_template=SUMMARIZE_SESSION_PROMPT,
            max_output_chars=4000,  # Large enough for context summary
            usage_tracker=self.usage_tracker,
        )

        self.repo.compact_session(self.current_session.id, compacted_content)
        return True
