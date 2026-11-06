import pytest
from fastapi import HTTPException

from app.main import require_read_access


def test_read_access_rejects_wrong_key_in_configured_environment(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_ACCESS_KEY", "expected")
    with pytest.raises(HTTPException) as error:
        require_read_access("wrong")
    assert error.value.status_code == 401


def test_read_access_accepts_configured_key(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_ACCESS_KEY", "expected")
    assert require_read_access("expected") is None
