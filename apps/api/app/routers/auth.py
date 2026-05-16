from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import User
from app.schemas import UserRead
from app.services.auth import (
    OAUTH_STATE_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    AuthError,
    build_google_authorization_url,
    create_session,
    exchange_google_code,
    fetch_google_profile,
    generate_state_token,
    revoke_session_token,
    upsert_google_user,
    user_for_session_token,
)

router = APIRouter(tags=["auth"])


def _frontend_redirect(query: dict[str, str] | None = None) -> str:
    settings = get_settings()
    if not query:
        return settings.frontend_url
    return f"{settings.frontend_url}?{urlencode(query)}"


def _set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    max_age = settings.auth_session_days * 24 * 60 * 60
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
    )


def _clear_state_cookie(response: Response) -> None:
    response.delete_cookie(
        OAUTH_STATE_COOKIE_NAME,
        path="/api/auth",
        samesite="lax",
    )


def current_user(
    db: Session = Depends(get_db),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> User:
    user = user_for_session_token(db, session_token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="로그인이 필요합니다.",
        )
    return user


@router.get("/api/auth/google/start")
def start_google_login() -> RedirectResponse:
    settings = get_settings()
    state = generate_state_token()
    try:
        url = build_google_authorization_url(settings, state)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        OAUTH_STATE_COOKIE_NAME,
        state,
        max_age=10 * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/api/auth",
    )
    return response


@router.get("/api/auth/google-callback")
@router.get("/api/auth/google/callback")
def finish_google_login(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
    expected_state: str | None = Cookie(
        default=None, alias=OAUTH_STATE_COOKIE_NAME
    ),
) -> RedirectResponse:
    if error:
        response = RedirectResponse(
            _frontend_redirect({"auth_error": error}),
            status_code=status.HTTP_302_FOUND,
        )
        _clear_state_cookie(response)
        return response

    if not code or not state or not expected_state or state != expected_state:
        response = RedirectResponse(
            _frontend_redirect({"auth_error": "invalid_state"}),
            status_code=status.HTTP_302_FOUND,
        )
        _clear_state_cookie(response)
        return response

    settings = get_settings()
    try:
        tokens = exchange_google_code(settings, code)
        access_token = str(tokens.get("access_token") or "")
        if not access_token:
            raise AuthError("Google access token을 확인할 수 없습니다.")
        profile = fetch_google_profile(access_token)
        user = upsert_google_user(db, profile)
        session_token, _session = create_session(
            db, user, session_days=settings.auth_session_days
        )
        db.commit()
    except AuthError:
        db.rollback()
        response = RedirectResponse(
            _frontend_redirect({"auth_error": "google_login_failed"}),
            status_code=status.HTTP_302_FOUND,
        )
        _clear_state_cookie(response)
        return response

    response = RedirectResponse(
        _frontend_redirect({"auth": "success"}),
        status_code=status.HTTP_302_FOUND,
    )
    _set_session_cookie(response, session_token)
    _clear_state_cookie(response)
    return response


@router.post("/api/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    db: Session = Depends(get_db),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> Response:
    revoke_session_token(db, session_token)
    db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_session_cookie(response)
    return response


@router.get("/api/me", response_model=UserRead)
def get_me(user: User = Depends(current_user)) -> UserRead:
    return UserRead.model_validate(user)
