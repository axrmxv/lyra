"""Тесты secret-сканера (FR-6): позитивы по типам, негативы, отсутствие утечки.

Фикстурные «секреты» собираются конкатенацией в runtime: gitleaks сканирует
статичный текст и не должен срабатывать на репозитории (единственное
исключение из правила «находка = стоп» не требуется).
"""

from lyra.ingest.secrets_scan import scan_text

# Синтетические фикстуры (не реальные ключи), собранные из частей
FAKE_AWS_KEY = "AKIA" + "IOSFODNN7REALKEY"
FAKE_GH_TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
FAKE_DSN = "postgresql" + "://admin:sup3rs3cret@db.corp.ru:5432/prod"
FAKE_PASSWORD_LINE = "password" + ' = "Qwerty123456"'


def test_detects_aws_access_key() -> None:
    findings = scan_text(f"Ключ доступа: {FAKE_AWS_KEY} для сервиса")
    assert any(f.kind == "aws_access_key" for f in findings)


def test_detects_private_key() -> None:
    header = "-----BEGIN RSA " + "PRIVATE KEY-----"
    text = f"{header}\nMIIEpAIBAAKCAQEA\n-----END RSA PRIVATE KEY-----"
    assert any(f.kind == "private_key" for f in scan_text(text))


def test_detects_github_token() -> None:
    assert any(f.kind == "github_token" for f in scan_text(f"token = {FAKE_GH_TOKEN}"))


def test_detects_connection_string_with_password() -> None:
    assert any(f.kind == "connection_string" for f in scan_text(f"dsn: {FAKE_DSN}"))


def test_detects_password_assignment() -> None:
    assert any(
        f.kind == "password_assignment"
        for f in scan_text(f"в конфиге указать {FAKE_PASSWORD_LINE}")
    )


def test_clean_text_passes() -> None:
    text = (
        "Политика отпусков: 28 дней в первый год. Пароль от Wi-Fi выдаёт ИТ-отдел. "
        "Подключение к базе описано в разделе Настройка. AKIA — префикс ключей AWS."
    )
    assert scan_text(text) == []


def test_finding_context_does_not_leak_secret() -> None:
    findings = scan_text(f"key: {FAKE_AWS_KEY}")
    assert findings
    for finding in findings:
        assert FAKE_AWS_KEY not in finding.context
