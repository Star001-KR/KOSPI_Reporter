"""Tests for symbol research-source resolution and per-user ownership."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from fastapi import HTTPException

from app.database import Base, _backfill_symbol_owner
from app.models import AnalysisResult, Disclosure, NewsItem, Symbol, User
from app.routers.symbols import (
    _symbol_detail,
    create_symbol,
    delete_symbol,
    get_symbol,
    get_symbol_price_history,
    list_symbols,
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

    def test_reads_are_scoped_to_the_owner(self) -> None:
        owner = self._user("owner@example.com")
        intruder = self._user("intruder@example.com")
        mine = create_symbol(
            SymbolCreate(market="KOSPI", code="005930", name="삼성전자"),
            db=self.db,
            user=owner,
        )

        # The owner sees their symbol in the list and can open it.
        listed = list_symbols(db=self.db, user=owner)
        self.assertEqual([s.id for s in listed], [mine.id])
        self.assertEqual(get_symbol(mine.id, db=self.db, user=owner).id, mine.id)

        # A different account sees an empty list and 404s on the id (404, not
        # 403, so it cannot probe which ids exist).
        self.assertEqual(list_symbols(db=self.db, user=intruder), [])
        for endpoint in (get_symbol, get_symbol_price_history):
            with self.assertRaises(HTTPException) as ctx:
                endpoint(mine.id, db=self.db, user=intruder)
            self.assertEqual(ctx.exception.status_code, 404)

    def test_unowned_symbols_are_hidden_from_reads(self) -> None:
        user = self._user("user@example.com")
        orphan = Symbol(market="KOSPI", code="000660", name="SK하이닉스")
        self.db.add(orphan)
        self.db.commit()

        self.assertEqual(list_symbols(db=self.db, user=user), [])
        with self.assertRaises(HTTPException) as ctx:
            get_symbol(orphan.id, db=self.db, user=user)
        self.assertEqual(ctx.exception.status_code, 404)


class BackfillSymbolOwnerTests(unittest.TestCase):
    """The legacy-owner backfill claims pre-auth unowned symbols for the lone user."""

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

    def _add_orphan(self, code: str) -> Symbol:
        symbol = Symbol(market="KOSPI", code=code, name=code)
        self.db.add(symbol)
        self.db.commit()
        return symbol

    def test_single_user_claims_all_unowned_symbols(self) -> None:
        user = User(email="solo@example.com")
        self.db.add(user)
        self.db.commit()
        a = self._add_orphan("005930")
        b = self._add_orphan("000660")

        _backfill_symbol_owner(bind=self.engine)

        self.db.expire_all()
        self.assertEqual(self.db.get(Symbol, a.id).owner_user_id, user.id)
        self.assertEqual(self.db.get(Symbol, b.id).owner_user_id, user.id)

    def test_multiple_users_leaves_ownership_untouched(self) -> None:
        self.db.add_all([User(email="a@example.com"), User(email="b@example.com")])
        self.db.commit()
        orphan = self._add_orphan("005930")

        _backfill_symbol_owner(bind=self.engine)

        self.db.expire_all()
        self.assertIsNone(self.db.get(Symbol, orphan.id).owner_user_id)

    def test_no_users_leaves_ownership_untouched(self) -> None:
        orphan = self._add_orphan("005930")

        _backfill_symbol_owner(bind=self.engine)

        self.db.expire_all()
        self.assertIsNone(self.db.get(Symbol, orphan.id).owner_user_id)


class AnalysisOrphanCleanupTests(unittest.TestCase):
    """Removing a symbol / news / disclosure must clear its analysis rows.

    ``AnalysisResult`` references its target by ``(target_type, target_id)``
    with no foreign key, so ``before_delete`` hooks on NewsItem/Disclosure are
    responsible for keeping ``analysis_results`` free of orphans.
    """

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

    def _add_analysis(self, target_type: str, target_id: int) -> None:
        self.db.add(
            AnalysisResult(
                target_type=target_type,
                target_id=target_id,
                summary="요약",
                sentiment="neutral",
                importance=3,
                portfolio_impact="영향 없음",
            )
        )
        self.db.commit()

    def test_deleting_a_news_item_clears_only_its_analysis(self) -> None:
        symbol = Symbol(market="KOSPI", code="005930", name="삼성전자")
        self.db.add(symbol)
        self.db.commit()
        kept = NewsItem(
            symbol_id=symbol.id,
            title="유지",
            original_url="https://news.example.com/keep",
            canonical_url="https://news.example.com/keep",
        )
        doomed = NewsItem(
            symbol_id=symbol.id,
            title="삭제",
            original_url="https://news.example.com/drop",
            canonical_url="https://news.example.com/drop",
        )
        self.db.add_all([kept, doomed])
        self.db.commit()
        self._add_analysis("news", kept.id)
        self._add_analysis("news", doomed.id)

        self.db.delete(doomed)
        self.db.commit()

        # Only the deleted item's analysis is gone; its sibling's remains.
        remaining = self.db.execute(select(AnalysisResult.target_id)).scalars().all()
        self.assertEqual(remaining, [kept.id])

    def test_deleting_a_symbol_clears_news_and_disclosure_analysis(self) -> None:
        owner = User(email="owner@example.com")
        self.db.add(owner)
        self.db.commit()
        symbol = Symbol(
            market="KOSPI", code="005930", name="삼성전자", owner_user_id=owner.id
        )
        self.db.add(symbol)
        self.db.commit()
        news = NewsItem(
            symbol_id=symbol.id,
            title="뉴스",
            original_url="https://news.example.com/a",
            canonical_url="https://news.example.com/a",
        )
        disclosure = Disclosure(
            symbol_id=symbol.id,
            rcept_no="20260101000001",
            report_name="주요사항보고서",
            original_url="https://dart.example.com/a",
        )
        self.db.add_all([news, disclosure])
        self.db.commit()
        self._add_analysis("news", news.id)
        self._add_analysis("disclosure", disclosure.id)

        delete_symbol(symbol.id, db=self.db, user=owner)

        # Symbol cascade removes its news/disclosures, and the hooks take the
        # matching analysis rows with them — no orphans left behind.
        self.assertEqual(self.db.execute(select(AnalysisResult)).scalars().all(), [])
        self.assertEqual(self.db.execute(select(NewsItem)).scalars().all(), [])
        self.assertEqual(self.db.execute(select(Disclosure)).scalars().all(), [])


if __name__ == "__main__":
    unittest.main()
