#!/usr/bin/env bash
# Runs every check. The end-to-end tests need Dedale: `DEDALE` (a path), or
# `dedale` on the PATH; they are skipped without it.
set -euo pipefail
cd "$(dirname "$0")/.."

step() { printf '\n==> %s\n' "$*"; }

step "compile"
python3 -m compileall -q tools tests

step "tests"
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -t . "$@"

if command -v actionlint >/dev/null; then
    step "workflows"
    actionlint
fi

step "all checks passed"
