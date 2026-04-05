#!/bin/bash
set -e

# Automatically set up Python virtual environment to avoid PEP 668 externally managed environment block.
VENV_DIR="/tmp/thesis-plot-venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment in $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
    echo "Installing dependencies..."
    "$VENV_DIR/bin/pip" install -q matplotlib pandas
fi

# Run the python script using the venv's python
"$VENV_DIR/bin/python" "$(dirname "$0")/plot_results.py" "$@"
