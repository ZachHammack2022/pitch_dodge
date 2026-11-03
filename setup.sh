#!/usr/bin/env bash
# One-time setup: creates .venv and installs Pitch Dodge into it.
# Works on macOS and Linux. Re-run it any time to update dependencies.
set -euo pipefail
cd "$(dirname "$0")"

find_python() {
  for cmd in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cmd" >/dev/null 2>&1 &&
       "$cmd" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      echo "$cmd"
      return 0
    fi
  done
  return 1
}

if ! PY=$(find_python); then
  echo "Pitch Dodge needs Python 3.10 or newer, and none was found."
  if [[ "$(uname)" == "Darwin" ]]; then
    echo "On a Mac, the easiest way is Homebrew (https://brew.sh):"
    echo "    brew install python@3.12"
    echo "or download an installer from https://www.python.org/downloads/macos/"
  fi
  exit 1
fi

echo "Using $("$PY" --version) ($(command -v "$PY"))"

if [[ ! -x .venv/bin/python ]]; then
  echo "Creating virtual environment in .venv ..."
  "$PY" -m venv .venv
fi

echo "Installing dependencies (the first time takes a minute) ..."
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -e .

echo
echo "All set. To play in your browser, run:"
echo "    ./play.sh"
echo "then open http://localhost:8000 (it opens automatically)."
