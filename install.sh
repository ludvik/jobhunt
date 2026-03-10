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
AGENT_WS="$HOME/.openclaw/agents/jobhunt-apply/workspace"
if ! openclaw agents list 2>/dev/null | grep -q "jobhunt-apply"; then
  mkdir -p "$AGENT_WS"
  openclaw agents add jobhunt-apply --non-interactive --workspace "$AGENT_WS"
  # Remove default scaffolded files — agent workspace should only contain SKILL.md
  rm -f "$AGENT_WS"/{AGENTS.md,BOOTSTRAP.md,HEARTBEAT.md,IDENTITY.md,SOUL.md,TOOLS.md,USER.md}
  rm -rf "$AGENT_WS"/{memory,.git,.openclaw}
  echo "Created openclaw agent: jobhunt-apply (cleaned default files)"
else
  echo "Agent jobhunt-apply already exists — skipping."
fi

# Symlink SKILL.md into the agent's workspace
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
