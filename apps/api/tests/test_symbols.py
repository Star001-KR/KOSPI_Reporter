"""Tests for symbol research-source resolution (preferred → common stock)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Symbol
from app.routers.symbols import research_symbol_id
from app.services.symbol_catalog import ListedSymbol

_RUNTIME_CATALOG = (
    ListedSymbol("KOSPI", "005930", "삼성전자"),
    ListedSymbol("KOSPI", "005935", "삼성전자우"),
)


class ResearchSymbolIdTests(unittest.TestCase):
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

    def _add(self, code: str, name: str) -> Symbol:
        symbol = Symbol(market="KOSPI", code=code, name=name)
        self.db.add(symbol)
        self.db.commit()
        return symbol

    def test_preferred_redirects_to_registered_common(self) -> None:
        common = self._add("005930", "삼성전자")
        preferred = self._add("005935", "삼성전자우")
        with patch(
            "app.services.symbol_catalog.listed_symbols", return_value=_RUNTIME_CATALOG
        ):
            # 삼성전자우 reads the common stock's research rows.
            self.assertEqual(research_symbol_id(self.db, preferred), common.id)
            # A common stock maps to itself.
            self.assertEqual(research_symbol_id(self.db, common), common.id)

    def test_preferred_without_common_uses_itself(self) -> None:
        preferred = self._add("005935", "삼성전자우")
        with patch(
            "app.services.symbol_catalog.listed_symbols", return_value=_RUNTIME_CATALOG
        ):
            # No common stock registered — the preferred symbol owns its rows.
            self.assertEqual(research_symbol_id(self.db, preferred), preferred.id)


if __name__ == "__main__":
    unittest.main()
