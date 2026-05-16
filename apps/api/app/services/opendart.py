"""OpenDART corp code import service (MVP-01).

OpenDART publishes the full mapping between its internal ``corp_code`` and the
listed ``stock_code`` as a zipped XML archive (``corpCode.xml``). This module
downloads that archive, parses it, and upserts the result into the
``dart_corp_codes`` table so registered KOSPI/KOSDAQ symbols can be resolved to
their OpenDART ``corp_code``.

The archive is parsed with the pure-Python ``html.parser`` instead of
``xml.etree`` so the importer carries no dependency on the expat C extension.
"""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urlencode
from urllib.request import urlopen

from sqlalchemy import select
from sqlalchemy.orm import Session

from kospi_core import DisclosureDraft

from app.config import get_settings
from app.models import CollectionRun, DartCorpCode, Disclosure, Symbol, utcnow

CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
OPENDART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
DART_VIEWER_URL = "https://dart.fss.or.kr/dsaf001/main.do"

CORP_CODE_RUN_TYPE = "corp_code_import"
DISCLOSURE_RUN_TYPE = "disclosure_collection"

_DOWNLOAD_TIMEOUT_SECONDS = 60.0
_REQUEST_TIMEOUT_SECONDS = 30.0
_DISCLOSURE_LOOKBACK_DAYS = 30
_DISCLOSURE_PAGE_COUNT = 100


class OpenDartError(RuntimeError):
    """Raised when an OpenDART request cannot be completed."""


@dataclass(frozen=True)
class CorpCodeEntry:
    """A single corp_code record parsed from the OpenDART archive."""

    corp_code: str
    corp_name: str
    stock_code: str | None
    modified_at: datetime | None


class _CorpCodeXMLParser(HTMLParser):
    """Collects the flat ``<list>`` records from the corpCode XML document."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.records: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._field: str | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag == "list":
            self._current = {}
            self._field = None
        elif self._current is not None:
            self._field = tag
            self._current.setdefault(tag, "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "list":
            if self._current is not None:
                self.records.append(self._current)
            self._current = None
            self._field = None
        elif tag == self._field:
            self._field = None

    def handle_data(self, data: str) -> None:
        if self._current is not None and self._field is not None:
            self._current[self._field] += data


def _parse_yyyymmdd(value: str | None) -> datetime | None:
    text = (value or "").strip()
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_corp_code_xml(xml_bytes: bytes) -> list[CorpCodeEntry]:
    """Parse the corpCode XML payload into CorpCodeEntry records."""
    parser = _CorpCodeXMLParser()
    parser.feed(xml_bytes.decode("utf-8", errors="replace"))
    parser.close()

    entries: list[CorpCodeEntry] = []
    for record in parser.records:
        corp_code = record.get("corp_code", "").strip()
        corp_name = record.get("corp_name", "").strip()
        if not corp_code or not corp_name:
            continue
        stock_code = record.get("stock_code", "").strip()
        entries.append(
            CorpCodeEntry(
                corp_code=corp_code,
                corp_name=corp_name,
                stock_code=stock_code or None,
                modified_at=_parse_yyyymmdd(record.get("modify_date")),
            )
        )
    return entries


def _between(text: str, start: str, end: str) -> str:
    lo = text.find(start)
    if lo < 0:
        return ""
    lo += len(start)
    hi = text.find(end, lo)
    return text[lo:hi].strip() if hi >= 0 else ""


def _describe_error_body(body: bytes) -> str:
    """Build a message from an OpenDART error body returned instead of a zip."""
    text = body.decode("utf-8", errors="replace")
    status = _between(text, "<status>", "</status>")
    message = _between(text, "<message>", "</message>")
    if status or message:
        return f"OpenDART 오류 (status={status or '?'}): {message or '메시지 없음'}"
    return "OpenDART 응답이 zip 형식이 아닙니다."


def extract_corp_code_xml(zip_bytes: bytes) -> bytes:
    """Return the XML payload contained in the OpenDART zip archive.

    A rejected API key makes OpenDART return a small XML error body instead of
    a zip; that case is surfaced as an :class:`OpenDartError`.
    """
    if not zipfile.is_zipfile(io.BytesIO(zip_bytes)):
        raise OpenDartError(_describe_error_body(zip_bytes))
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        xml_names = [
            name for name in archive.namelist() if name.lower().endswith(".xml")
        ]
        if not xml_names:
            raise OpenDartError("OpenDART 응답 zip에 XML 파일이 없습니다.")
        return archive.read(xml_names[0])


def download_corp_code_zip(api_key: str) -> bytes:
    """Download the corpCode.xml zip archive from OpenDART."""
    url = f"{CORP_CODE_URL}?{urlencode({'crtfc_key': api_key})}"
    try:
        with urlopen(url, timeout=_DOWNLOAD_TIMEOUT_SECONDS) as response:
            return response.read()
    except OSError as exc:
        raise OpenDartError(
            f"OpenDART corpCode 아카이브 다운로드에 실패했습니다: {exc}"
        ) from exc


def upsert_corp_codes(db: Session, entries: Iterable[CorpCodeEntry]) -> tuple[int, int]:
    """Insert new corp codes and refresh existing ones.

    Returns ``(inserted, updated)``. Existing rows are matched by ``corp_code``
    and updated in place, so repeated imports never create duplicate rows.
    """
    existing = {
        row.corp_code: row for row in db.execute(select(DartCorpCode)).scalars()
    }
    inserted = 0
    updated = 0
    for entry in entries:
        row = existing.get(entry.corp_code)
        if row is None:
            row = DartCorpCode(corp_code=entry.corp_code)
            db.add(row)
            existing[entry.corp_code] = row
            inserted += 1
        else:
            updated += 1
        row.corp_name = entry.corp_name
        row.stock_code = entry.stock_code
        if entry.modified_at is not None:
            row.modified_at = entry.modified_at
    return inserted, updated


def _mark_run_failed(db: Session, run: CollectionRun, message: str) -> None:
    run.status = "failed"
    run.finished_at = utcnow()
    run.message = message
    db.commit()


def run_corp_code_import(
    db: Session,
    *,
    api_key: str | None = None,
    downloader: Callable[[str], bytes] | None = None,
) -> CollectionRun:
    """Run a corp code import and record it as a :class:`CollectionRun`.

    ``api_key`` defaults to the configured ``OPENDART_API_KEY``; pass an
    explicit value (including ``""``) to override it. ``downloader`` is
    injectable for tests. The run row is committed before the work starts so a
    failure still leaves an audit trail in ``collection_runs``.
    """
    if api_key is None:
        api_key = get_settings().opendart_api_key
    if downloader is None:
        downloader = download_corp_code_zip

    run = CollectionRun(run_type=CORP_CODE_RUN_TYPE, status="running")
    db.add(run)
    db.commit()

    try:
        if not api_key:
            raise OpenDartError(
                "OPENDART_API_KEY가 설정되지 않아 corp code import를 실행할 수 없습니다."
            )
        xml_bytes = extract_corp_code_xml(downloader(api_key))
        entries = parse_corp_code_xml(xml_bytes)
        if not entries:
            raise OpenDartError("OpenDART corpCode 응답에서 corp code를 찾지 못했습니다.")
        inserted, updated = upsert_corp_codes(db, entries)
        run.status = "success"
        run.symbols_processed = len(entries)
        run.finished_at = utcnow()
        run.message = (
            f"corp code import 완료: 신규 {inserted}건, 갱신 {updated}건, "
            f"전체 {len(entries)}건."
        )
        db.commit()
    except OpenDartError as exc:
        db.rollback()
        _mark_run_failed(db, run, str(exc))
    except Exception as exc:  # broad: any failure must still be recorded
        db.rollback()
        _mark_run_failed(db, run, f"corp code import 중 예상치 못한 오류: {exc}")
    return run


# --- disclosures (MVP-02) ------------------------------------------------


def resolve_corp_code(db: Session, stock_code: str) -> str | None:
    """Look up the OpenDART corp_code mapped to a registered stock code."""
    return (
        db.execute(
            select(DartCorpCode.corp_code).where(
                DartCorpCode.stock_code == stock_code
            )
        )
        .scalars()
        .first()
    )


def _http_get_json(url: str) -> dict:
    """GET a URL and decode the JSON body, raising OpenDartError on failure."""
    try:
        with urlopen(url, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            payload = response.read()
    except OSError as exc:
        raise OpenDartError(f"OpenDART 요청에 실패했습니다: {exc}") from exc
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise OpenDartError(
            f"OpenDART 응답을 JSON으로 해석할 수 없습니다: {exc}"
        ) from exc
    if not isinstance(decoded, dict):
        raise OpenDartError("OpenDART 응답 형식이 올바르지 않습니다.")
    return decoded


def _disclosure_list_from_response(data: dict) -> list[dict]:
    """Apply OpenDART status codes and return the raw disclosure list.

    ``status`` ``"000"`` is success and ``"013"`` means no matching data (an
    empty list, not an error); any other status becomes an OpenDartError.
    """
    status = str(data.get("status", ""))
    if status == "013":
        return []
    if status != "000":
        raise OpenDartError(
            f"OpenDART list.json 오류 (status={status}): "
            f"{data.get('message') or '메시지 없음'}"
        )
    items = data.get("list", [])
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def fetch_disclosure_list(
    api_key: str, corp_code: str, bgn_de: str, end_de: str
) -> list[dict]:
    """Fetch the first page of recent disclosures for a corp_code from OpenDART."""
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bgn_de": bgn_de,
        "end_de": end_de,
        "page_no": "1",
        "page_count": str(_DISCLOSURE_PAGE_COUNT),
    }
    data = _http_get_json(f"{OPENDART_LIST_URL}?{urlencode(params)}")
    return _disclosure_list_from_response(data)


def parse_disclosures(raw_list: Iterable[dict]) -> list[DisclosureDraft]:
    """Convert raw OpenDART disclosure rows into DisclosureDraft records."""
    drafts: list[DisclosureDraft] = []
    for raw in raw_list:
        rcept_no = str(raw.get("rcept_no", "")).strip()
        report_name = str(raw.get("report_nm", "")).strip()
        if not rcept_no or not report_name:
            continue
        drafts.append(
            DisclosureDraft(
                rcept_no=rcept_no,
                report_name=report_name,
                original_url=f"{DART_VIEWER_URL}?{urlencode({'rcpNo': rcept_no})}",
                corp_code=str(raw.get("corp_code", "")).strip() or None,
                corp_name=str(raw.get("corp_name", "")).strip() or None,
                submitted_at=_parse_yyyymmdd(raw.get("rcept_dt")),
                raw_payload=raw,
            )
        )
    return drafts


def store_disclosures(
    db: Session, symbol_id: int, drafts: Iterable[DisclosureDraft]
) -> int:
    """Insert disclosure drafts, skipping any ``rcept_no`` already stored.

    Returns the number of newly inserted rows. ``rcept_no`` is globally unique,
    so re-collecting the same period never creates duplicate rows.
    """
    inserted = 0
    seen: set[str] = set()
    for draft in drafts:
        if draft.rcept_no in seen:
            continue
        seen.add(draft.rcept_no)
        already_stored = db.execute(
            select(Disclosure.id).where(Disclosure.rcept_no == draft.rcept_no)
        ).first()
        if already_stored is not None:
            continue
        db.add(
            Disclosure(
                symbol_id=symbol_id,
                rcept_no=draft.rcept_no,
                report_name=draft.report_name,
                corp_code=draft.corp_code,
                corp_name=draft.corp_name,
                submitted_at=draft.submitted_at,
                original_url=draft.original_url,
                raw_payload=draft.raw_payload,
            )
        )
        inserted += 1
    return inserted


def _default_disclosure_fetcher(
    api_key: str,
) -> Callable[[str, str, str], list[dict]]:
    def fetch(corp_code: str, bgn_de: str, end_de: str) -> list[dict]:
        return fetch_disclosure_list(api_key, corp_code, bgn_de, end_de)

    return fetch


def _run_summary(
    label: str, total: int, processed: int, inserted: int, failures: list[str]
) -> str:
    summary = f"{label}: 종목 {processed}/{total} 처리, 신규 {inserted}건."
    if failures:
        summary += f" 실패 {len(failures)}건 — " + "; ".join(failures)
    return summary


def collect_disclosures(
    db: Session,
    *,
    api_key: str | None = None,
    fetcher: Callable[[str, str, str], list[dict]] | None = None,
    lookback_days: int = _DISCLOSURE_LOOKBACK_DAYS,
) -> CollectionRun:
    """Collect recent OpenDART disclosures for every registered symbol.

    The result is recorded as a :class:`CollectionRun`. Symbols without a
    mapped corp_code or with a failing request are reported in ``message``
    while disclosures that did succeed are still stored (partial success).
    """
    if api_key is None:
        api_key = get_settings().opendart_api_key

    run = CollectionRun(run_type=DISCLOSURE_RUN_TYPE, status="running")
    db.add(run)
    db.commit()

    try:
        if not api_key:
            raise OpenDartError(
                "OPENDART_API_KEY가 설정되지 않아 공시 수집을 실행할 수 없습니다."
            )

        active_fetcher = fetcher or _default_disclosure_fetcher(api_key)
        symbols = list(db.execute(select(Symbol)).scalars())
        today = date.today()
        bgn_de = (today - timedelta(days=lookback_days)).strftime("%Y%m%d")
        end_de = today.strftime("%Y%m%d")

        processed = 0
        inserted_total = 0
        failures: list[str] = []
        for symbol in symbols:
            corp_code = resolve_corp_code(db, symbol.code)
            if corp_code is None:
                failures.append(f"{symbol.name}({symbol.code}): corp_code 미매핑")
                continue
            try:
                raw = active_fetcher(corp_code, bgn_de, end_de)
                inserted_total += store_disclosures(
                    db, symbol.id, parse_disclosures(raw)
                )
                processed += 1
            except OpenDartError as exc:
                failures.append(f"{symbol.name}({symbol.code}): {exc}")

        run.symbols_processed = processed
        run.disclosures_inserted = inserted_total
        run.finished_at = utcnow()
        run.status = "failed" if symbols and processed == 0 else "success"
        run.message = _run_summary(
            "공시 수집", len(symbols), processed, inserted_total, failures
        )
        db.commit()
    except OpenDartError as exc:
        db.rollback()
        _mark_run_failed(db, run, str(exc))
    except Exception as exc:  # broad: any failure must still be recorded
        db.rollback()
        _mark_run_failed(db, run, f"공시 수집 중 예상치 못한 오류: {exc}")
    return run
