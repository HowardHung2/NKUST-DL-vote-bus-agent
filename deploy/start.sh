#!/bin/bash
# Start the help desk on 127.0.0.1:7860. Cloudflare Tunnel connects to it from the same machine.
# PYTHON: the Python that has the packages in requirements.txt (default: python3).
cd "$(dirname "$0")/.." || exit 1
mkdir -p logs
exec "${PYTHON:-python3}" -u app.py >> logs/app.log 2>&1
