#!/usr/bin/env bash
# install.sh — set up the jobhunt tool
# Usage: bash install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${HOME}/.openclaw/data/jobhunt"
SKILLS_DIR="${HOME}/.openclaw/skills/jobhunt"

echo "==> Installing jobhunt dependencies..."
cd "${SCRIPT_DIR}"
uv sync

echo "==> Installing Playwright Chromium..."
uv run playwright install chromium

echo "==> Creating data directories..."
mkdir -p "${DATA_DIR}/session"
mkdir -p "${DATA_DIR}/resumes"
mkdir -p "${DATA_DIR}/prompts"

echo "==> Installing default prompt templates..."
for f in classify.md tailor.md analyze.md; do
    if [ ! -f "${DATA_DIR}/prompts/${f}" ]; then
        cp "${SCRIPT_DIR}/prompts/${f}" "${DATA_DIR}/prompts/${f}"
        echo "    ${f} → ${DATA_DIR}/prompts/${f}"
    else
        echo "    ${f} already exists, skipping"
    fi
done

echo "==> Installing SKILL.md..."
mkdir -p "${SKILLS_DIR}"
cp "${SCRIPT_DIR}/SKILL.md" "${SKILLS_DIR}/SKILL.md"
echo "    SKILL.md → ${SKILLS_DIR}/SKILL.md"

echo ""
echo "✓ jobhunt installed."
echo ""
echo "  Run:  uv run jobhunt --help"
echo "  Auth: uv run jobhunt auth"
echo "  Tip:  Add 'alias jobhunt=\"uv run jobhunt\"' to your shell profile."
