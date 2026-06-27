"""Shared fixtures for the HA-aware value_crossing tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading the value_crossing custom integration in every test."""
    yield
