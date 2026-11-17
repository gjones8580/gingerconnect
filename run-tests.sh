#!/usr/bin/env bash
# Run the GingerConnect test suite using the project venv
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

if ! .venv/bin/python -c "import pytest" 2>/dev/null; then
    echo "Installing dev dependencies..."
    .venv/bin/pip install -q -r requirements-dev.txt
fi

exec .venv/bin/python -m pytest "$@"
