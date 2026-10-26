#!/bin/sh
# RunnasUP local app: builds the React frontend, then serves it and the API on http://127.0.0.1:8600.
#   ./run.sh              personal database  data/runrank.sqlite  (or $RUNRANK_DB)
#   ./run.sh demo         separate synthetic demo database  data/demo/runrank-demo.sqlite
#   ./run.sh demo-reset   delete and recreate the demo database only
# Stop with Ctrl+C. Nothing is deployed; the server only listens on 127.0.0.1.
set -e
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { echo "Missing .venv: run  python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.lock"; exit 1; }
[ -d web/node_modules ] || npm --prefix web ci
npm --prefix web run build >/dev/null
case "${1:-}" in
  demo)       exec .venv/bin/python -m runrank.serve --demo ;;
  demo-reset) exec .venv/bin/python -m runrank.serve --demo --reset-demo ;;
  "")         exec .venv/bin/python -m runrank.serve ;;
  *)          echo "usage: ./run.sh [demo|demo-reset]"; exit 2 ;;
esac
