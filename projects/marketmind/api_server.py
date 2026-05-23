"""MarketMind API Server — thin entry point.

Start: python api_server.py
Then open: http://localhost:8520

All route definitions are in api/routes.py.
Data access is in api/data_providers.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Workspace root on path so `from marketmind.xxx` imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.data_providers import add_log_entry  # noqa: E402


if __name__ == "__main__":
    import uvicorn
    from api.routes import app

    add_log_entry("info", "MarketMind API server starting")
    import os as _os
    host = _os.environ.get("MARKETMIND_HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=8520, log_level="info")
