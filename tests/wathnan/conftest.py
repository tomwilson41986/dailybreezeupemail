import datetime as dt
import sys
from dataclasses import replace
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
# The golden-report fixture is imported by name from several test modules.
sys.path.insert(0, str(FIXTURES))


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture
def config():
    from wathnan.config import build_config
    return build_config(today=dt.date(2026, 8, 13))


@pytest.fixture
def any_owner_config(config):
    """A config that treats every owner as Wathnan, to exercise the parsers."""
    return replace(config, owner_aliases=("",))
