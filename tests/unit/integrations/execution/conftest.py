"""Optional execution SDK doubles for protocol tests."""

import sys
import types
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def boxlite_stub(monkeypatch: pytest.MonkeyPatch):
    """Mock the optional SDK without importing it or starting a VM."""
    module = types.ModuleType("boxlite")
    module.Boxlite = MagicMock()
    module.Options = MagicMock()
    monkeypatch.setitem(sys.modules, "boxlite", module)
