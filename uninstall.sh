#!/usr/bin/env bash
set -euo pipefail

echo "Uninstalling jobhunt agent and browser isolation..."

# Remove openclaw agent
if openclaw agents list 2>/dev/null | grep -q "jobhunt-apply"; then
  openclaw agents delete jobhunt-apply
  echo "Deleted openclaw agent: jobhunt-apply"
else
  echo "Agent jobhunt-apply not found — skipping."
fi

# Remove browser profile
if openclaw browser profiles 2>/dev/null | grep -q "^jobhunt:"; then
  openclaw browser delete-profile --name jobhunt
  echo "Deleted browser profile: jobhunt"
else
  echo "Browser profile jobhunt not found — skipping."
fi

echo "Uninstall complete."
