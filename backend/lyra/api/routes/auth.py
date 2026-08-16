"""POST /auth/login, GET /auth/me (docs/api-contract.md §1)."""

from fastapi import APIRouter, Depends

from lyra.api.deps import CurrentUserDep, SessionDep, login_rate_limit
from lyra.api.schemas.auth import LoginRequest, LoginResponse, UserOut
from lyra.core.auth import create_access_token, verify_password, verify_password_dummy
from lyra.core.config import get_settings
from lyra.core.constants import DEFAULT_TENANT_ID
from lyra.core.errors import UnauthorizedError
from lyra.db.repositories import UserRepository

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", dependencies=[Depends(login_rate_limit)])
async def login(body: LoginRequest, session: SessionDep) -> LoginResponse:
    user = await UserRepository(session).get_by_email(DEFAULT_TENANT_ID, body.email)
    # Единое сообщение и одинаковое время ответа для "нет пользователя",
    # "неверный пароль" и "деактивирован" — какие email существуют, эндпоинт
    # не раскрывает ни текстом, ни задержкой (docs/security-and-access.md §7)
    if user is None:
        verify_password_dummy()
        raise UnauthorizedError("Неверный email или пароль")
    if not verify_password(body.password, user.password_hash) or not user.is_active:
        raise UnauthorizedError("Неверный email или пароль")
    token, expires_in = create_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        secret=get_settings().jwt_secret,
    )
    return LoginResponse(
        access_token=token, expires_in=expires_in, user=UserOut.model_validate(user)
    )


@router.get("/me")
async def me(user: CurrentUserDep) -> UserOut:
    return UserOut.model_validate(user)
