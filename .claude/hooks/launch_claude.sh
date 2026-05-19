#!/bin/bash
# Launch script for Claude Code — runs pre-session validator first.
# Usage: bash "E:/AI_Studio_Workspace/.claude/hooks/launch_claude.sh"

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE="E:/AI_Studio_Workspace"

echo "=== Pre-Session Check ==="
python "${WORKSPACE}/.claude/hooks/pre_session.py"
RC=$?

if [ $RC -ne 0 ]; then
    echo ""
    echo "Pre-session check FAILED (exit code $RC)."
    echo "Fix the issues above, then re-run."
    exit $RC
fi

echo ""
echo "Pre-session check PASSED. Launching Claude Code..."
echo ""

exec claude "$@"
