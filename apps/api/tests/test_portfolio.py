"""Per-user scoping for the portfolio brief.

The brief must reflect only the caller's own symbols, holdings and latest
activity — never another account's. These call the router function directly
(like the other unit tests) with an explicit ``user``.
"""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Holding, NewsItem, Symbol, User
from app.routers.portfolio import get_portfolio_brief


class PortfolioBriefScopingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _user(self, email: str) -> User:
        user = User(email=email)
        self.db.add(user)
        self.db.commit()
        return user

    def _symbol(self, owner: User | None, code: str, name: str, value: float) -> Symbol:
        symbol = Symbol(
            market="KOSPI",
            code=code,
            name=name,
            owner_user_id=owner.id if owner else None,
        )
        self.db.add(symbol)
        self.db.flush()
        self.db.add(Holding(symbol_id=symbol.id, market_value=value))
        self.db.add(
            NewsItem(
                symbol_id=symbol.id,
                title=f"{name} 뉴스",
                original_url=f"https://news.example.com/{code}",
                canonical_url=f"https://news.example.com/{code}",
            )
        )
        self.db.commit()
        return symbol

    def test_brief_only_includes_callers_symbols(self) -> None:
        alice = self._user("alice@example.com")
        bob = self._user("bob@example.com")
        self._symbol(alice, "005930", "삼성전자", 1000.0)
        self._symbol(bob, "000660", "SK하이닉스", 9999.0)
        self._symbol(None, "035420", "NAVER", 5000.0)  # seeded / unowned

        brief = get_portfolio_brief(db=self.db, user=alice)

        self.assertEqual(brief.total_symbols, 1)
        self.assertEqual(brief.total_market_value, 1000.0)
        self.assertEqual([p.symbol.code for p in brief.positions], ["005930"])
        # Latest items must not surface Bob's or the seeded symbol's news.
        self.assertTrue(all(item.symbol_name == "삼성전자" for item in brief.latest_items))

    def test_brief_is_empty_for_a_user_with_no_symbols(self) -> None:
        loner = self._user("loner@example.com")
        self._symbol(self._user("other@example.com"), "005930", "삼성전자", 1000.0)

        brief = get_portfolio_brief(db=self.db, user=loner)

        self.assertEqual(brief.total_symbols, 0)
        self.assertEqual(brief.total_market_value, 0)
        self.assertEqual(brief.positions, [])
        self.assertEqual(brief.latest_items, [])


if __name__ == "__main__":
    unittest.main()
