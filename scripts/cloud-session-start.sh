#!/usr/bin/env bash
# SessionStart hook (see .claude/settings.json). Only does anything in a
# Claude Code cloud session: installs the test toolchain CI uses, then prints
# the global rules so they land in Claude's context. Locally it exits at once.
[ "$CLAUDE_CODE_REMOTE" = "true" ] || exit 0

root="$CLAUDE_PROJECT_DIR"
log=/tmp/cloud-session-start.log
(
  set -e
  # Brain: Python package + dev tools (pytest, ruff), same as CI.
  cd "$root/brain" && pip install -q -e ".[dev]"
  # Addon: Lua 5.1 (what WoW runs) and busted, from Ubuntu's archive
  # (luarocks.org isn't on the cloud network allowlist).
  if ! command -v busted >/dev/null; then
    apt-get update -qq && apt-get install -y -qq lua5.1 lua-busted
  fi
) >"$log" 2>&1 || echo "Cloud setup hit an error; see $log before running tests."

cat "$root/docs/agents/global-rules.md"
