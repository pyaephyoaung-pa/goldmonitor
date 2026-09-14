import os, sys
# Make repo-root modules importable when running pytest from anywhere.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import signals
import storage


@pytest.fixture(autouse=True)
def _fresh_caches():
    """storage and signals each cache for one logical run; a test session is
    one process, so clear both around every test."""
    storage.reset_cache()
    signals.reset_cache()
    yield
    storage.reset_cache()
    signals.reset_cache()
