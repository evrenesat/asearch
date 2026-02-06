CRITICAL - Security

  - src/asky/tools.py:220-221 - Shell injection vulnerability: subprocess.run(cmd_str, shell=True) with user-controlled args. Should use shell=False with args # NO, we need shell=True, also we trust the user input here.

  HIGH - Potential Bugs

  - tools.py:60, 100 - Bare Exception catches without logging context
  - core/api_client.py:159-161 - HTTPError.response used without null-check
  - storage/sqlite.py:81 - init_db() called on every write (performance overhead)
  - html.py:38-47 - handle_data() adds orphaned text to links list incorrectly

  MEDIUM - Code Quality

  - cli/main.py:268-280 - Redundant history is not None check
  - cli/utils.py:92-141 - Uppercase parameter names violate PEP 8
  - summarization.py:73-74 - Duplicate comment lines
  - tools.py:123-150 - set() deduplication loses URL ordering

  LOW - Type Hints

  - cli/history.py:63-69 - Missing -> None return type
  - storage/interface.py:137, 142, 147 - Missing return type hints on abstract methods

  Test Coverage Gaps

  - No tests for shell command execution with metacharacters
  - No tests for concurrent SQLite access
  - No tests for malformed LLM JSON responses
  - No tests for max turns exit path (cli/chat.py:141-176)



  [ ] Delete old cacahe entries from research cache table on startup. ResearchCache.cleanup_expired()
  [] research on file/directory