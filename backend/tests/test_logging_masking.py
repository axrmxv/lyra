"""Маскирование чувствительных полей в логах (security-and-access §5)."""

from lyra.core.logging import _mask_sensitive


def test_sensitive_keys_masked() -> None:
    event = {
        "event": "login",
        "password": "p@ssw0rd",
        "api_key": "sk-123",
        "confluence_token": "xoxb-abc",
        "authorization": "Bearer jwt",
        "user_email": "a@b.c",
    }
    masked = _mask_sensitive(None, "info", dict(event))
    assert masked["password"] == "***"
    assert masked["api_key"] == "***"
    assert masked["confluence_token"] == "***"  # подстрока token
    assert masked["authorization"] == "***"
    assert masked["user_email"] == "a@b.c"  # обычные поля не трогаются
    assert masked["event"] == "login"


def test_masking_is_case_insensitive_and_substring() -> None:
    masked = _mask_sensitive(None, "info", {"JWT_Secret": "x", "PromptTokens": 5})
    assert masked["JWT_Secret"] == "***"
    # prompt_tokens содержит "token" — маскируется (осознанный компромисс:
    # ложные срабатывания дешевле утечки)
    assert masked["PromptTokens"] == "***"
