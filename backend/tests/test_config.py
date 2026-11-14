import pytest
from pydantic import ValidationError

from backend.config import ConfigError, Settings

from .conftest import make_settings


def test_live_mode_reports_missing_names_only():
    with pytest.raises((ConfigError, ValidationError)) as info:
        make_settings(app_mode="live", storage_backend="sqlite")
    message = str(info.value)
    assert "OPENAI_API_KEY" in message and "ANIMAL_API_KEY" in message and "STORAGE_BACKEND=supabase" in message


def test_redis_url_must_be_connection_url():
    with pytest.raises(ValidationError) as info:
        make_settings(redis_url="10.0.0.0/24")
    assert "REDIS_URL" in str(info.value)


def test_animal_key_alias_and_https(monkeypatch):
    monkeypatch.setenv("ANIMAL_API_SERVICE_KEY", "alias-key")
    monkeypatch.setenv("ANIMAL_API_BASE_URL", "http://apis.data.go.kr/1543061/abandonmentPublicService_v2")
    s = Settings(_env_file=None)
    assert s.animal_api_key.get_secret_value() == "alias-key"
    assert s.animal_api_base_url.startswith("https://")
    assert s.animal_data_source == "api"
    monkeypatch.setenv("ANIMAL_API_KEY", "primary-key")
    assert Settings(_env_file=None).animal_api_key.get_secret_value() == "primary-key"


def test_cookie_secure_follows_mode():
    assert make_settings().cookie_secure is False
    assert make_settings(auth_cookie_secure=True).cookie_secure is True


def test_samesite_none_requires_secure():
    with pytest.raises((ConfigError, ValidationError)):
        make_settings(auth_cookie_samesite="none", auth_cookie_secure=False)


def test_secrets_not_in_repr():
    s = make_settings(openai_api_key="sk-test-secret")
    assert "sk-test-secret" not in repr(s)
