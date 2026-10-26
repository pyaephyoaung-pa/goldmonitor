import os, sys
# Make repo-root modules importable when running pytest from anywhere.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import bot_core
import gta
import signals
import storage


@pytest.fixture(autouse=True)
def _fresh_caches():
    """storage and signals cache for one logical run, and bot_core remembers
    rate-limit refusals for the life of the process. A test session is one
    process, so clear all of it around every test."""
    storage.reset_cache()
    signals.reset_cache()
    gta.reset_cache()
    # Offline by default: every monitor run and /price would otherwise call
    # goldtraders.or.th. tests/test_gta.py resets this and mocks the request.
    gta._fetched = True
    bot_core._refused_until.clear()
    yield
    storage.reset_cache()
    signals.reset_cache()
    gta.reset_cache()
    bot_core._refused_until.clear()
