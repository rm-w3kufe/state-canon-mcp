#!/usr/bin/env python3
"""Launcher — lets any MCP client run the server with one absolute path,
no PYTHONPATH games, no cwd requirements.

    python3 /abs/path/to/state-canon/mcp_server.py --state /abs/path/state.json
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from state_canon.server import main  # noqa: E402

if __name__ == "__main__":
    main()
