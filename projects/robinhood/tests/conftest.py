"""
conftest.py - Pytest configuration for Robinhood project tests.

Adds the project root (parent of tests/) to sys.path so that
'src.account_reader' imports resolve correctly.
"""

import sys
from pathlib import Path

# Add the project root directory (grandparent of conftest.py) to sys.path
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))