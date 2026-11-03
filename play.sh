#!/usr/bin/env bash
# Start the Pitch Dodge server and open it in your browser.
# Any options are passed through, e.g. ./play.sh --port 8080
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/pitch-dodge ]]; then
  echo "Run ./setup.sh first."
  exit 1
fi
exec .venv/bin/pitch-dodge serve "$@"
