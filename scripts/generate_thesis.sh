#!/usr/bin/env bash
# generate_thesis.sh — Wrapper to run generate_thesis_graphs.py in a venv
# Automatically creates + caches the Python virtual environment.
# Usage: ./scripts/generate_thesis.sh [--dry-run] [--results-dir <path>] [--out-dir <path>]
set -euo pipefail

VENV_DIR="/tmp/thesis-plot-venv"
DEPS="matplotlib pandas numpy seaborn"

# ── Setup venv if needed ────────────────────────────────────────────────────
if [ ! -f "$VENV_DIR/bin/python" ]; then
    echo "⚙️  Creating Python virtual environment at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
    echo "📦 Installing dependencies ($DEPS)..."
    "$VENV_DIR/bin/pip" install -q $DEPS
    echo "✅ Environment ready."
fi

# ── Run the graph generator ─────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo ""
echo "🚀 Running thesis graph generator..."
echo ""
"$VENV_DIR/bin/python" "$SCRIPT_DIR/generate_thesis_graphs.py" "$@"
