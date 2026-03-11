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

echo "jobhunt installed."
echo "Run: uv run --directory $SKILL_DIR python scripts/pipeline.py --help"
echo "Or:  uv run --directory $SKILL_DIR python scripts/cli.py --help"
