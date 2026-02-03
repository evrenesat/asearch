import pytest
import sqlite3
import os
from pathlib import Path
from unittest.mock import patch, MagicMock
from asky.storage import (
    init_db,
    save_interaction,
    get_history,
    get_interaction_context,
    delete_messages,
    delete_sessions,
)


@pytest.fixture
def temp_db_path(tmp_path):
    # Create a temporary database path
    db_file = tmp_path / "test_history.db"
    return db_file


@pytest.fixture
def mock_db_path(temp_db_path):
    # Mock the DB_PATH constant in storage implementations
    with (
        patch("asky.storage.sqlite.DB_PATH", temp_db_path),
        patch("asky.storage.session.DB_PATH", temp_db_path),
    ):
        yield temp_db_path


def test_init_db(mock_db_path):
    init_db()
    assert mock_db_path.exists()

    conn = sqlite3.connect(mock_db_path)
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='history'")
    assert c.fetchone() is not None
    conn.close()


def test_save_and_get_history(mock_db_path):
    init_db()
    save_interaction(
        query="test query",
        answer="test answer",
        model="test_model",
        query_summary="q sum",
        answer_summary="a sum",
    )

    rows = get_history(limit=1)
    assert len(rows) == 1
    # Interaction indexing: 0:id, 1:timestamp, 2:query, 3:query_summary, 4:answer_summary, 5:answer, 6:model
    assert rows[0][2] == "test query"
    assert rows[0][3] == "q sum"
    assert rows[0][4] == "a sum"
    assert rows[0][5] == "test answer"
    assert rows[0][6] == "test_model"


def test_get_interaction_context(mock_db_path):
    init_db()
    # Use a query longer than the default threshold (160)
    save_interaction("q1" * 100, "a1", "m1", "qs1", "as1")

    # Get the ID of the inserted row
    rows = get_history(1)
    rid = rows[0][0]

    context = get_interaction_context([rid])
    assert "Query" in context
    assert "qs1" in context
    assert "as1" in context

    context_full = get_interaction_context([rid], full=True)
    assert "a1" in context_full


def test_cleanup_db(mock_db_path, capsys):
    init_db()
    # Insert 3 records
    for i in range(3):
        save_interaction(f"q{i}", f"a{i}", "m")

    # Verify insert
    assert len(get_history(10)) == 3

    # Test deletion by ID
    rows = get_history(10)
    ids = [r[0] for r in rows]
    target_id = ids[0]

    delete_messages(str(target_id))
    assert len(get_history(10)) == 2

    # Test delete all
    delete_messages(delete_all=True)
    assert len(get_history(10)) == 0


def test_cleanup_db_edge_cases(mock_db_path, capsys):
    init_db()
    ids = []
    for i in range(5):
        save_interaction(f"q{i}", f"a{i}", "m")

    rows = get_history(10)  # 5,4,3,2,1
    # Test reverse range 4-2
    delete_messages("4-2")

    remaining = get_history(10)
    assert len(remaining) == 2
    rem_ids = sorted([r[0] for r in remaining])
    # The IDs in DB are likely 1,2,3,4,5. `cleanup_db("4-2")` deletes 2,3,4.
    # So 1 and 5 should remain.
    # Wait, `get_history` returns DESC.
    # Let's verify IDs explicitly if we can rely on autoincrement.
    # Note: SQLite `sqlite_sequence` is not reset unless we did delete_all, which we didn't in this test func (new mock_db_path).

    # We can assume IDs are 1..5

    # Let's check remaining count first
    assert len(remaining) == 2

    # Test invalid range
    delete_messages("a-b")
    captured = capsys.readouterr()
    assert "Error: Invalid range format" in captured.out

    # Test invalid list
    delete_messages("1,a")
    captured = capsys.readouterr()
    assert "Error: Invalid list format" in captured.out

    # Test invalid ID
    delete_messages("abc")
    captured = capsys.readouterr()
    assert "Error: Invalid ID format" in captured.out


def test_delete_sessions(mock_db_path):
    from asky.storage.session import SessionRepository

    repo = SessionRepository()
    init_db()

    # Create 3 sessions
    sid1 = repo.create_session("model", name="s1")
    sid2 = repo.create_session("model", name="s2")
    sid3 = repo.create_session("model", name="s3")

    # Add messages to sid1
    repo.add_message(sid1, "user", "hi", "hi", 10)

    # Verify messages exist
    assert len(repo.get_session_messages(sid1)) == 1

    # Test delete session 1
    delete_sessions(str(sid1))
    assert repo.get_session_by_id(sid1) is None
    assert len(repo.get_session_messages(sid1)) == 0

    # Test delete all
    delete_sessions(delete_all=True)
    assert repo.get_session_by_id(sid2) is None
    assert repo.get_session_by_id(sid3) is None
