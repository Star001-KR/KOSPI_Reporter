"""Tests for symbol research-source resolution and per-user ownership."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from fastapi import HTTPException

from app.database import Base
from app.models import NewsItem, Symbol, User
from app.routers.symbols import (
    _symbol_detail,
    create_symbol,
    delete_symbol,
    research_symbol_ids,
    update_symbol,
)
from app.schemas import SymbolCreate, SymbolPatch
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


class SymbolOwnershipTests(unittest.TestCase):
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

    def test_only_the_registrant_can_modify_a_symbol(self) -> None:
        owner = self._user("owner@example.com")
        intruder = self._user("intruder@example.com")
        created = create_symbol(
            SymbolCreate(market="KOSPI", code="005930", name="삼성전자"),
            db=self.db,
            user=owner,
        )

        # A different account can neither edit nor delete it.
        with self.assertRaises(HTTPException) as patch_ctx:
            update_symbol(
                created.id, SymbolPatch(memo="침입"), db=self.db, user=intruder
            )
        self.assertEqual(patch_ctx.exception.status_code, 403)

        with self.assertRaises(HTTPException) as delete_ctx:
            delete_symbol(created.id, db=self.db, user=intruder)
        self.assertEqual(delete_ctx.exception.status_code, 403)

        # The registrant can.
        updated = update_symbol(
            created.id, SymbolPatch(memo="내 메모"), db=self.db, user=owner
        )
        self.assertEqual(updated.memo, "내 메모")

    def test_symbol_without_an_owner_cannot_be_modified(self) -> None:
        user = self._user("user@example.com")
        orphan = Symbol(market="KOSPI", code="000660", name="SK하이닉스")
        self.db.add(orphan)
        self.db.commit()

        with self.assertRaises(HTTPException) as ctx:
            update_symbol(orphan.id, SymbolPatch(memo="x"), db=self.db, user=user)
        self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
