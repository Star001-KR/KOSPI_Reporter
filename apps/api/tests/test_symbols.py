"""Tests for symbol research-source resolution (preferred → common stock)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import NewsItem, Symbol
from app.routers.symbols import _symbol_detail, research_symbol_ids
from app.services.symbol_catalog import ListedSymbol

_RUNTIME_CATALOG = (
    ListedSymbol("KOSPI", "005930", "삼성전자"),
    ListedSymbol("KOSPI", "005935", "삼성전자우"),
)


class ResearchSymbolIdsTests(unittest.TestCase):
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

    def test_common_and_preferred_share_one_research_set(self) -> None:
        common = self._add("005930", "삼성전자")
        preferred = self._add("005935", "삼성전자우")
        with patch(
            "app.services.symbol_catalog.listed_symbols", return_value=_RUNTIME_CATALOG
        ):
            shared = sorted([common.id, preferred.id])
            # Either sibling resolves to the union of both ids.
            self.assertEqual(research_symbol_ids(self.db, preferred), shared)
            self.assertEqual(research_symbol_ids(self.db, common), shared)

    def test_preferred_without_common_uses_itself(self) -> None:
        preferred = self._add("005935", "삼성전자우")
        with patch(
            "app.services.symbol_catalog.listed_symbols", return_value=_RUNTIME_CATALOG
        ):
            # No common stock registered — the preferred symbol owns its rows.
            self.assertEqual(research_symbol_ids(self.db, preferred), [preferred.id])

    def test_news_collected_onto_preferred_survives_late_common_registration(
        self,
    ) -> None:
        """Regression: a collection run can store the common stock's news under
        the preferred stock when the preferred is registered first. Once the
        common stock is registered too, both feeds must still surface that news
        instead of going permanently empty."""
        preferred = self._add("005935", "삼성전자우")
        self.db.add(
            NewsItem(
                symbol_id=preferred.id,
                title="삼성전자 신규 라인 가동",
                original_url="https://news.example.com/a",
                canonical_url="https://news.example.com/a",
            )
        )
        self.db.commit()
        # The common stock is registered only afterward.
        common = self._add("005930", "삼성전자")

        with patch(
            "app.services.symbol_catalog.listed_symbols", return_value=_RUNTIME_CATALOG
        ):
            common_titles = [
                entry.item.title
                for entry in _symbol_detail(self.db, common).news_items
            ]
            preferred_titles = [
                entry.item.title
                for entry in _symbol_detail(self.db, preferred).news_items
            ]

        self.assertIn("삼성전자 신규 라인 가동", common_titles)
        self.assertIn("삼성전자 신규 라인 가동", preferred_titles)


if __name__ == "__main__":
    unittest.main()
