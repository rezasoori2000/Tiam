import pytest

from app import secrets_store


def test_no_key_means_unavailable(monkeypatch):
    monkeypatch.delenv(secrets_store.ENV_VAR, raising=False)
    monkeypatch.setattr(secrets_store, "_windows_user_env", lambda name: None)  # nor in the Windows user env
    assert not secrets_store.available()
    with pytest.raises(secrets_store.SecretKeyMissing):
        secrets_store.encrypt("sk-test")


def test_roundtrip_and_ciphertext_differs(monkeypatch):
    monkeypatch.setenv(secrets_store.ENV_VAR, secrets_store.generate_key())
    token = secrets_store.encrypt("sk-ant-1234567890")
    assert "1234567890" not in token
    assert secrets_store.decrypt(token) == "sk-ant-1234567890"
    assert secrets_store.decrypt(None) is None


def test_wrong_key_fails_loudly(monkeypatch):
    monkeypatch.setenv(secrets_store.ENV_VAR, secrets_store.generate_key())
    token = secrets_store.encrypt("secret-value")
    monkeypatch.setenv(secrets_store.ENV_VAR, secrets_store.generate_key())
    with pytest.raises(secrets_store.InvalidToken):
        secrets_store.decrypt(token)


def test_last4_hides_short_secrets():
    assert secrets_store.last4("sk-ant-abcdWXYZ") == "WXYZ"
    assert secrets_store.last4("short") == ""


def test_windows_user_env_used_when_process_env_lacks_it(monkeypatch):
    key = secrets_store.generate_key()
    monkeypatch.delenv(secrets_store.ENV_VAR, raising=False)
    monkeypatch.setattr(secrets_store, "_windows_user_env", lambda name: key)
    assert secrets_store.decrypt(secrets_store.encrypt("x")) == "x"
