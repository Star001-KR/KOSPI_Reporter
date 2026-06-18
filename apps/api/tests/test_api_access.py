"""HTTP-level access control: every data API requires a valid session.

These exercise the FastAPI router stack (unlike the unit tests, which call
router functions directly), so they verify the router-level
``Depends(current_user)`` guard actually returns 401 to unauthenticated
callers and 200 once a session cookie is presented.
"""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import User
from app.services.auth import SESSION_COOKIE_NAME, create_session

# Data endpoints that must reject anonymous callers — one GET per protected
# router (symbols, portfolio, daily-reports, collections).
PROTECTED_GET_PATHS = (
    "/api/symbols",
    "/api/portfolio/brief",
    "/api/daily-reports",
    "/api/collections/runs",
)


class ApiAccessControlTests(unittest.TestCase):
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

        def override_get_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        # No `with` block: skip the lifespan so the real database is untouched.
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.engine.dispose()

    def _issue_session_cookie(self) -> str:
        db = self.session_factory()
        try:
            user = User(email="reader@example.com")
            db.add(user)
            db.commit()
            token, _session = create_session(db, user, session_days=30)
            db.commit()
        finally:
            db.close()
        return token

    def test_data_endpoints_require_authentication(self) -> None:
        for path in PROTECTED_GET_PATHS:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401)

    def test_health_stays_public(self) -> None:
        self.assertEqual(self.client.get("/api/health").status_code, 200)

    def test_valid_session_is_authorized(self) -> None:
        self.client.cookies.set(SESSION_COOKIE_NAME, self._issue_session_cookie())
        response = self.client.get("/api/symbols")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])


if __name__ == "__main__":
    unittest.main()
