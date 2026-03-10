#!/usr/bin/env bash
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="${HOME}/.openclaw/data/jobhunt"

# Create data dirs
mkdir -p "$DATA_DIR"/{resumes,profile,session,logs,apply-log}
mkdir -p "$DATA_DIR"/agents/{tailor,apply}

# Install Python deps
cd "$SKILL_DIR"
uv sync

# Install Playwright browsers
uv run playwright install chromium

# ── Agent setup ───────────────────────────────────────────────────────────────

# Create openclaw agent 'jobhunt-apply' (idempotent)
if ! openclaw agents list 2>/dev/null | grep -q "jobhunt-apply"; then
  openclaw agents add --name jobhunt-apply
  echo "Created openclaw agent: jobhunt-apply"
else
  echo "Agent jobhunt-apply already exists — skipping."
fi

# Symlink SKILL.md into the agent's workspace
AGENT_WS="$HOME/.openclaw/agents/jobhunt-apply/workspace"
mkdir -p "$AGENT_WS"
ln -sf "$SKILL_DIR/SKILL.md" "$AGENT_WS/SKILL.md"
echo "Symlinked SKILL.md → $AGENT_WS/SKILL.md"

# ── Browser profile setup ─────────────────────────────────────────────────────

# Create browser profile 'jobhunt' (idempotent)
if ! openclaw browser profiles 2>/dev/null | grep -q "^jobhunt:"; then
  openclaw browser create-profile --name jobhunt --color "#2196F3"
  echo "Created browser profile: jobhunt"
else
  echo "Browser profile jobhunt already exists — skipping."
fi

echo ""
echo "jobhunt installed."
echo "Run: uv run --directory $SKILL_DIR python scripts/pipeline.py --help"
echo "Or:  uv run --directory $SKILL_DIR python scripts/cli.py --help"
