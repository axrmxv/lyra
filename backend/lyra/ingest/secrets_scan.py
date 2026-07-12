"""Сканер секретов при ingest (docs/security-and-access.md §5, FR-6).

Находка = документ не индексируется (job failed_pii). Паттерны — высокоточные
сигнатуры ключей/токенов; сканер не отключается и не ослабляется
(.claude/rules/api.md).
"""

import re
from dataclasses import dataclass

_PATTERNS: dict[str, re.Pattern[str]] = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "aws_secret_key": re.compile(
        r"(?i)aws.{0,20}(?:secret|private).{0,20}['\"][0-9a-zA-Z/+=]{40}['\"]"
    ),
    "gcp_api_key": re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    "github_token": re.compile(r"\bgh[pousr]_[0-9A-Za-z]{36,}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[0-9A-Za-z\-]{10,}\b"),
    "jwt_like": re.compile(r"\beyJ[0-9A-Za-z_\-]{10,}\.eyJ[0-9A-Za-z_\-]{10,}\.[0-9A-Za-z_\-]+\b"),
    "connection_string": re.compile(
        r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s:@/]+:[^\s@/]+@"
    ),
    "password_assignment": re.compile(
        r"(?i)\b(?:password|passwd|pwd)\s*[:=]\s*['\"][^'\"\s]{8,}['\"]"
    ),
}


@dataclass
class SecretFinding:
    kind: str
    context: str  # обрезанный фрагмент вокруг находки БЕЗ самого секрета


def scan_text(text: str) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for kind, pattern in _PATTERNS.items():
        for match in pattern.finditer(text):
            start = max(0, match.start() - 30)
            prefix = text[start : match.start()].replace("\n", " ")
            # Секрет в отчёт не попадает — только тип и контекст слева
            findings.append(SecretFinding(kind=kind, context=f"...{prefix}[{kind}]"))
    return findings
