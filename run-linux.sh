#!/usr/bin/env bash
set -euo pipefail
CLICKY_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -x "$CLICKY_ROOT/.venv/bin/python" ]]; then
  echo "Create the virtual environment first; see docs/LINUX_SETUP.md." >&2
  exit 1
fi
cd "$CLICKY_ROOT"
exec "$CLICKY_ROOT/.venv/bin/python" "$CLICKY_ROOT/main.py" "$@"
