"""Unit tests for social-login user/session helpers."""

from __future__ import annotations

from datetime import timedelta
import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import AuthSession, User, UserIdentity, utcnow
from app.services.auth import (
    GOOGLE_PROVIDER,
    create_session,
    email_is_allowed,
    revoke_session_token,
    user_for_session_token,
    user_from_google_token_payload,
)


class AuthServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(
            bind=self.engine, autoflush=False, autocommit=False
        )
        self.db = self.session_factory()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_upserts_google_user_identity(self) -> None:
        first = user_from_google_token_payload(
            self.db,
            {
                "sub": "google-1",
                "email": "investor@example.com",
                "name": "Investor",
                "picture": "https://example.com/avatar.png",
            },
        )
        self.db.commit()

        second = user_from_google_token_payload(
            self.db,
            {
                "sub": "google-1",
                "email": "investor@example.com",
                "name": "Investor Updated",
                "picture": "https://example.com/avatar-2.png",
            },
        )
        self.db.commit()

        self.assertEqual(first.id, second.id)
        self.assertEqual(second.display_name, "Investor Updated")
        self.assertEqual(
            len(self.db.execute(select(User)).scalars().all()),
            1,
        )
        identity = self.db.execute(select(UserIdentity)).scalar_one()
        self.assertEqual(identity.provider, GOOGLE_PROVIDER)
        self.assertEqual(identity.provider_user_id, "google-1")

    def test_session_token_resolves_and_revokes(self) -> None:
        user = user_from_google_token_payload(
            self.db,
            {"sub": "google-2", "email": "reader@example.com"},
        )
        token, session = create_session(self.db, user, session_days=30)
        self.db.commit()

        resolved = user_for_session_token(self.db, token)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.id, user.id)  # type: ignore[union-attr]

        revoke_session_token(self.db, token)
        self.db.commit()
        self.assertIsNone(user_for_session_token(self.db, token))
        self.assertEqual(
            len(self.db.execute(select(AuthSession)).scalars().all()),
            0,
        )

    def test_expired_session_is_ignored(self) -> None:
        user = user_from_google_token_payload(
            self.db,
            {"sub": "google-3", "email": "old@example.com"},
        )
        token, session = create_session(self.db, user, session_days=30)
        session.expires_at = utcnow() - timedelta(days=1)
        self.db.commit()

        self.assertIsNone(user_for_session_token(self.db, token))


class EmailAllowlistTests(unittest.TestCase):
    def test_empty_allowlist_denies_everyone_by_default(self) -> None:
        # Fail closed: a forgotten allowlist must not become an open door.
        self.assertFalse(email_is_allowed((), "anyone@example.com"))
        self.assertFalse(email_is_allowed((), None))

    def test_empty_allowlist_permits_everyone_only_with_explicit_opt_in(self) -> None:
        self.assertTrue(email_is_allowed((), "anyone@example.com", allow_all=True))
        self.assertTrue(email_is_allowed((), None, allow_all=True))

    def test_opt_in_is_ignored_once_an_allowlist_is_configured(self) -> None:
        allowed = ("alice@example.com",)
        self.assertTrue(email_is_allowed(allowed, "alice@example.com", allow_all=True))
        self.assertFalse(email_is_allowed(allowed, "carol@example.com", allow_all=True))

    def test_configured_allowlist_restricts_to_listed_addresses(self) -> None:
        allowed = ("alice@example.com", "bob@example.com")
        self.assertTrue(email_is_allowed(allowed, "alice@example.com"))
        self.assertFalse(email_is_allowed(allowed, "carol@example.com"))

    def test_match_ignores_case_and_surrounding_whitespace(self) -> None:
        self.assertTrue(
            email_is_allowed(("alice@example.com",), "  Alice@Example.com  ")
        )

    def test_missing_email_rejected_when_allowlist_configured(self) -> None:
        self.assertFalse(email_is_allowed(("alice@example.com",), None))


if __name__ == "__main__":
    unittest.main()
