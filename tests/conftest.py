"""Pytest configuration and shared fixtures."""

import sys
from pathlib import Path

# Add the project root to the Python path so we can import systemd_unit_monitor
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))