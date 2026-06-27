"""Pytest configuration: ensure the repo root is importable.

Lets tests import ``custom_components.value_crossing.<module>`` directly. The
ARCH-01 modules (``kinds``, ``estimation``, ``const``) are Home-Assistant-free.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
