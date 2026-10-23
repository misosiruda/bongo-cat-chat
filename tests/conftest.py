"""Keep existing Korean UI fixtures independent of the CI host's language."""
from types import SimpleNamespace

import pytest

from bongo_chat import localization


@pytest.fixture(autouse=True)
def korean_system_language(monkeypatch):
    monkeypatch.setattr(localization, 'QLocale', SimpleNamespace(
        system=lambda: SimpleNamespace(uiLanguages=lambda: ['ko-KR'])))
