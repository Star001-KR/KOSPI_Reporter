"""Social-login authentication helpers.

The app uses provider identities only: no local passwords are stored. Google
OAuth creates or updates a local user row, then a random server-side session
token is stored as a hash and returned to the browser in an HttpOnly cookie.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import Settings
from app.models import AuthSession, User, UserIdentity, utcnow

SESSION_COOKIE_NAME = "kospi_session"
OAUTH_STATE_COOKIE_NAME = "kospi_oauth_state"

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_PROVIDER = "google"

_REQUEST_TIMEOUT_SECONDS = 30.0


class AuthError(RuntimeError):
    """Raised when an auth provider flow cannot be completed."""


class AuthNotAllowedError(AuthError):
    """Raised when a verified identity is not on the access allowlist."""


@dataclass(frozen=True)
class GoogleProfile:
    provider_user_id: str
    email: str | None
    display_name: str | None
    avatar_url: str | None
    raw_payload: dict


def generate_state_token() -> str:
    return secrets.token_urlsafe(32)


def email_is_allowed(
    allowed: tuple[str, ...], email: str | None, *, allow_all: bool = False
) -> bool:
    """Whether ``email`` may sign in, given the configured allowlist.

    Fails closed: an empty allowlist denies everyone unless ``allow_all`` is
    set (the explicit local-development escape hatch), so a forgotten
    ``AUTH_ALLOWED_EMAILS`` never silently turns the app into an open service.
    Once any address is configured, only those addresses may sign in (compared
    case-insensitively), and a profile without an email is rejected.
    """
    if not allowed:
        return allow_all
    if not email:
        return False
    return email.strip().lower() in allowed


def ensure_email_allowed(settings: Settings, email: str | None) -> None:
    """Raise :class:`AuthNotAllowedError` if ``email`` is not on the allowlist."""
    if not email_is_allowed(
        settings.auth_allowed_emails,
        email,
        allow_all=settings.auth_allow_all_signins,
    ):
        raise AuthNotAllowedError("이 계정은 접근이 허용되지 않았습니다.")


def build_google_authorization_url(settings: Settings, state: str) -> str:
    if not settings.google_oauth_client_id or not settings.google_oauth_client_secret:
        raise AuthError("Google OAuth 설정이 필요합니다.")

    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def _read_json_response(request: Request) -> dict:
    try:
        with urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            payload = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AuthError(f"Google OAuth 요청이 실패했습니다: HTTP {exc.code} {detail}") from exc
    except URLError as exc:
        raise AuthError(f"Google OAuth 요청에 실패했습니다: {exc.reason}") from exc
    except OSError as exc:
        raise AuthError(f"Google OAuth 요청에 실패했습니다: {exc}") from exc

    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise AuthError(f"Google OAuth 응답을 해석할 수 없습니다: {exc}") from exc

    if not isinstance(decoded, dict):
        raise AuthError("Google OAuth 응답 형식이 올바르지 않습니다.")
    return decoded


def exchange_google_code(settings: Settings, code: str) -> dict:
    if not settings.google_oauth_client_id or not settings.google_oauth_client_secret:
        raise AuthError("Google OAuth 설정이 필요합니다.")

    payload = urlencode(
        {
            "code": code,
            "client_id": settings.google_oauth_client_id,
            "client_secret": settings.google_oauth_client_secret,
            "redirect_uri": settings.google_oauth_redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    request = Request(
        GOOGLE_TOKEN_URL,
        data=payload,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    return _read_json_response(request)


def fetch_google_profile(access_token: str) -> GoogleProfile:
    request = Request(
        GOOGLE_USERINFO_URL,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
    )
    raw = _read_json_response(request)
    subject = str(raw.get("sub") or "").strip()
    if not subject:
        raise AuthError("Google 사용자 식별자를 확인할 수 없습니다.")

    email_value = str(raw.get("email") or "").strip() or None
    name_value = str(raw.get("name") or "").strip() or None
    picture_value = str(raw.get("picture") or "").strip() or None
    return GoogleProfile(
        provider_user_id=subject,
        email=email_value,
        display_name=name_value,
        avatar_url=picture_value,
        raw_payload=raw,
    )


def _profile_from_mapping(raw: Mapping[str, object]) -> GoogleProfile:
    subject = str(raw.get("sub") or "").strip()
    if not subject:
        raise AuthError("Google 사용자 식별자를 확인할 수 없습니다.")
    return GoogleProfile(
        provider_user_id=subject,
        email=str(raw.get("email") or "").strip() or None,
        display_name=str(raw.get("name") or "").strip() or None,
        avatar_url=str(raw.get("picture") or "").strip() or None,
        raw_payload=dict(raw),
    )


def user_from_google_token_payload(db: Session, raw_profile: Mapping[str, object]) -> User:
    """Upsert a user from an already-fetched Google profile mapping.

    This is mostly useful for tests and for future provider adapters that have
    already validated a profile payload upstream.
    """
    return upsert_google_user(db, _profile_from_mapping(raw_profile))


def upsert_google_user(db: Session, profile: GoogleProfile) -> User:
    identity = db.execute(
        select(UserIdentity)
        .options(joinedload(UserIdentity.user))
        .where(UserIdentity.provider == GOOGLE_PROVIDER)
        .where(UserIdentity.provider_user_id == profile.provider_user_id)
    ).scalar_one_or_none()

    now = utcnow()
    if identity is not None:
        user = identity.user
        identity.email = profile.email
        identity.raw_payload = profile.raw_payload
    else:
        user = None
        if profile.email:
            user = db.execute(
                select(User).where(User.email == profile.email)
            ).scalar_one_or_none()
        if user is None:
            user = User(email=profile.email)
            db.add(user)
            db.flush()
        identity = UserIdentity(
            user_id=user.id,
            provider=GOOGLE_PROVIDER,
            provider_user_id=profile.provider_user_id,
            email=profile.email,
            raw_payload=profile.raw_payload,
        )
        db.add(identity)

    user.email = profile.email or user.email
    user.display_name = profile.display_name or user.display_name
    user.avatar_url = profile.avatar_url or user.avatar_url
    user.last_login_at = now
    db.flush()
    return user


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(
    db: Session, user: User, *, session_days: int
) -> tuple[str, AuthSession]:
    token = secrets.token_urlsafe(48)
    now = utcnow()
    session = AuthSession(
        user_id=user.id,
        token_hash=hash_session_token(token),
        created_at=now,
        expires_at=now + timedelta(days=session_days),
        last_seen_at=now,
    )
    db.add(session)
    db.flush()
    return token, session


def user_for_session_token(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    session = db.execute(
        select(AuthSession)
        .options(joinedload(AuthSession.user))
        .where(AuthSession.token_hash == hash_session_token(token))
        .where(AuthSession.expires_at > utcnow())
    ).scalar_one_or_none()
    if session is None:
        return None
    return session.user


def revoke_session_token(db: Session, token: str | None) -> None:
    if not token:
        return
    session = db.execute(
        select(AuthSession).where(AuthSession.token_hash == hash_session_token(token))
    ).scalar_one_or_none()
    if session is not None:
        db.delete(session)
        db.flush()
