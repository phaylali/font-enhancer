#!/bin/bash
# Font Enhancer launcher script

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Create virtual environment if it doesn't exist
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
    echo "Creating virtual environment..."
    uv venv "$SCRIPT_DIR/.venv"
fi

# Install dependencies
echo "Installing dependencies..."
uv pip install -r "$SCRIPT_DIR/requirements.txt"

# Run the application using the venv Python
echo "Starting Font Enhancer..."
"$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/main.py" "$@"
