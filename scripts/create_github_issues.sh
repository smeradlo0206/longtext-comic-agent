#!/usr/bin/env bash
set -euo pipefail

echo "This helper expects gh CLI authentication and a GitHub remote."
echo "Create labels first, then copy issue bodies from docs/github_issues.md."
echo "Suggested labels:"
cat <<'LABELS'
area:schema
area:story
area:backend
area:workflow
area:visual
area:qa
area:frontend
type:feature
type:bug
type:docs
priority:p0
priority:p1
week:1
week:2
week:3
week:4
week:5
week:6
blocked
LABELS
