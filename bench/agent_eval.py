"""Headless Claude Code A/B runner (the headline benchmark).

Arm A: stock ``claude -p``, MCP disabled. Arm B: identical, with cortex MCP + CLAUDE.md steering.
Parses ``--output-format stream-json`` for tokens, tool calls, wall-clock; scores localization
recall/precision vs gold_files.

Filled in Phase 6.
"""
