"""Shared test fixtures."""

import pytest

from app.services import history_service


@pytest.fixture(autouse=True)
def _isolated_history_db(tmp_path, monkeypatch):
    """Point every test at a throwaway SQLite file so the real library is untouched."""
    monkeypatch.setattr(history_service, "_db_path", lambda: str(tmp_path / "history.db"))
