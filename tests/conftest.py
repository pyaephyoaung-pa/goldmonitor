import os, sys
# Make repo-root modules importable when running pytest from anywhere.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import storage


@pytest.fixture(autouse=True)
def _fresh_gist_cache():
    """storage caches the Gist for one logical run; a test session is one
    process, so clear it around every test."""
    storage.reset_cache()
    yield
    storage.reset_cache()
