"""Константы MVP."""

import uuid

# Единственный tenant MVP (PRD A-7); в production tenant_id приходит из JWT.
# Фиксированный UUID — детерминированный seed и предсказуемые тесты.
DEFAULT_TENANT_ID = uuid.UUID("00000000-0000-7000-8000-000000000001")
