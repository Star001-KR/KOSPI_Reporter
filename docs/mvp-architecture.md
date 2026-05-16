# MVP Architecture

## Goal

최종 목표는 일반 사용자가 구매한 도메인으로 접속해 KOSPI/KOSDAQ 종목의 최신 공시, 뉴스, 요약 분석을 확인할 수 있는 공개 웹사이트를 만드는 것이다. 장기적으로는 검색 유입, 재방문, 광고 수익화를 고려한다.

첫 MVP는 계좌 연동 없이 동작한다. 성공 기준은 데모 데이터가 아니라 실제 OpenDART 공시와 Naver 뉴스 검색 결과가 수집되고, 사용자가 웹에서 최신 투자 이슈와 분석 결과를 확인할 수 있는 상태다.

NH/NAMUH 계좌 어댑터는 MVP 이후 단계로 둔다.

## Product Direction

현재 코드는 개인 로컬 포트폴리오 리서치 도구에 가깝다. 최종 목표는 공개 사이트이므로 MVP를 두 단계로 나눈다.

1. Real Data Engine MVP: 실제 데이터 수집, 분석, 실행 이력을 완성한다.
2. Public Site MVP: 일반 사용자가 도메인으로 접속해 사용할 수 있게 배포, 사용자 데이터 경계, 공개 UX, 운영 안정성을 갖춘다.

광고 수익화는 Public Site MVP 이후에 붙인다. 단, 레이아웃과 정책 문서는 광고 슬롯, 개인정보/쿠키 안내, 트래픽 분석을 나중에 추가하기 쉬운 형태로 준비한다.

## Quick Start For Independent Sessions

새 세션은 아래 순서로 바로 작업을 시작한다.

1. 이 문서의 `Work Queue`에서 가장 앞의 `not-started` 또는 `in-progress` 티켓을 고른다.
2. 티켓의 `Files`, `Acceptance Criteria`, `Verification`을 먼저 읽고 구현 범위를 고정한다.
3. 기존 mock 흐름은 개발 보조 기능으로 유지하되, 실데이터 MVP 경로와 섞지 않는다.
4. 외부 API 키가 없으면 실제 API 호출 테스트 대신 fixture/mock 테스트를 추가하고, 키 부재 시 명확한 실패 메시지를 남긴다.
5. 완료 후 해당 티켓의 완료 조건을 이 문서에서 확인하고, 필요한 경우 체크 상태와 후속 작업을 갱신한다.

현재 실행 명령:

```bash
npm run api:dev
npm run api:test
npm run worker
npm run web:dev
npm run web:build
npm run verify
```

API 코드와 테스트는 추가 설치 없이 동작하도록 Python 표준 라이브러리만 사용한다. 외부 HTTP 호출은 `urllib`, 테스트는 `unittest` 기반이다. 새 런타임 의존성이 꼭 필요하면 `apps/api/requirements.txt`에 추가한다.

현재 환경 변수 후보는 `.env.example`에 있다.

- `OPENDART_API_KEY`
- `NAVER_CLIENT_ID`
- `NAVER_CLIENT_SECRET`
- `VITE_API_BASE_URL`

## Commercialization Notes

현재 repository가 public이고 license가 MIT인 점은 지금 단계의 구현 범위에서 제외한다. 어느 정도 목표가 달성된 뒤 저장소 공개 범위, 라이선스, 상업화 관련 문구를 별도 작업으로 정리한다.

현재 세션들은 라이선스/공개 저장소 상태를 이유로 MVP 작업을 막지 않는다.

## Real Data MVP Definition

Real Data Engine MVP는 아래 조건을 만족해야 완료로 본다.

- 사용자가 KOSPI/KOSDAQ 종목을 직접 등록한다.
- 등록 종목의 OpenDART `corp_code`가 매핑된다.
- 등록 종목별 최신 공시가 OpenDART에서 수집되어 `disclosures`에 저장된다.
- 등록 종목별 최신 뉴스가 Naver News Search API에서 수집되어 `news_items`에 저장된다.
- 수집된 원문에 대해 요약, 감성, 중요도, 포트폴리오 영향이 `analysis_results`에 저장된다.
- 수집/분석 실행 결과와 실패 사유가 `collection_runs`에 남는다.
- 웹 대시보드와 통합 피드가 mock 데이터 없이 실제 수집 데이터로 동작한다.

## Public Site MVP Definition

Public Site MVP는 아래 조건을 만족해야 완료로 본다.

- 사용자가 로컬 개발 서버가 아니라 실제 도메인으로 접속할 수 있다.
- HTTPS가 적용되어 있다.
- API 서버와 웹 앱이 공개 환경에서 안정적으로 동작한다.
- 일반 사용자가 가입 없이도 종목 검색, 최신 뉴스/공시, 분석 피드를 확인할 수 있다.
- 개인 보유 수량/평단 같은 민감할 수 있는 정보는 서버의 전역 데이터로 섞이지 않는다.
- 공개 사이트용 빈 상태, 오류 상태, API 키/수집 실패 상태가 사용자에게 이해 가능하게 표시된다.
- 검색 엔진이 읽을 수 있는 기본 metadata, sitemap, robots 정책을 갖춘다.
- 기본 analytics를 붙일 수 있는 구조가 있다.
- 광고 슬롯을 넣을 수 있는 레이아웃 여지를 확보하되, 광고 네트워크 연동은 MVP 이후로 둔다.

## Public User Data Boundary

공개 사이트에서는 현재의 `symbols`/`holdings` 구조를 그대로 열면 모든 사용자가 같은 서버 포트폴리오를 수정하는 문제가 생긴다. Public Site MVP 전에 아래 중 하나를 선택해야 한다.

권장 MVP 선택: 공개 데이터 + 브라우저 로컬 관심종목

- 서버는 종목별 뉴스/공시/분석 같은 공개 데이터를 저장한다.
- 사용자의 관심종목, 보유 수량, 평단은 브라우저 `localStorage` 또는 클라이언트 상태에만 저장한다.
- 로그인 없이 빠르게 공개 서비스를 열 수 있다.
- 광고 기반 공개 사이트와 잘 맞는다.

대안 1: 공개 읽기 전용 큐레이션

- 서버에 관리자가 고른 대표 종목만 저장한다.
- 일반 사용자는 등록/수정 없이 검색과 피드만 본다.
- 구현은 가장 단순하지만 개인화가 약하다.

대안 2: 로그인 기반 개인 포트폴리오

- 사용자별 계정, 인증, 권한, 개인정보 정책이 필요하다.
- 장기적으로는 좋지만 Public Site MVP에는 과하다.

이 문서의 Public Site MVP는 권장 MVP 선택을 기준으로 작성한다. 즉, 서버는 공개 리서치 데이터 저장소이고, 사용자별 관심/보유 정보는 MVP에서는 브라우저 로컬에 둔다.

## Non-Goals For MVP

- NH/NAMUH 계좌 연동
- 실시간 시세 연동
- 사용자 계정/인증
- 서버에 개인별 보유 수량/평단 저장
- 다중 포트폴리오
- 고급 LLM 평가 파이프라인
- 광고 네트워크 실제 승인/연동
- 유료 구독/결제
- 라이선스 변경 또는 repository 공개 범위 변경

## Current Slice

```text
Web UI
  -> Backend API
    -> symbols CRUD
    -> portfolio brief
    -> mock activity generation
  -> DB
    -> symbols
    -> holdings
    -> dart_corp_codes
    -> news_items
    -> disclosures
    -> analysis_results
    -> collection_runs
```

현재 slice는 UI/API 검증을 위한 mock activity를 포함한다. 실데이터 MVP에서는 mock activity가 개발 보조 기능으로 내려가고, OpenDART/Naver 수집과 분석 실행 경로가 같은 DB 테이블을 채운다.

## Code Map

- `apps/api/app/main.py`: FastAPI 앱, router 등록 위치
- `apps/api/app/config.py`: 환경 변수 설정 위치. collector 키와 공개 배포 설정을 여기에 추가한다.
- `apps/api/app/database.py`: SQLAlchemy engine/session, 현재는 `create_all` 방식
- `apps/api/app/models.py`: MVP DB 모델 전체
- `apps/api/app/schemas.py`: API 응답/요청 Pydantic 모델
- `apps/api/app/routers/symbols.py`: 종목 CRUD, 상세 조회, 현재 mock activity endpoint
- `apps/api/app/routers/portfolio.py`: 대시보드 brief API
- `apps/api/app/routers/dev.py`: 개발용 seed endpoint
- `apps/api/app/services/mock_data.py`: 개발용 mock 수집/분석 생성
- `apps/api/app/services/symbol_catalog.py`: 현재 정적 종목 검색 목록
- `apps/web/src/api.ts`: 프론트 API client
- `apps/web/src/App.tsx`: 대시보드, 통합 피드, 등록 모달, 현재 mock 수집 호출
- `workers/scheduler.py`: scheduler placeholder

## Domain Tables

- `symbols`: 현재는 서버 저장 종목. Public Site MVP에서는 공개 수집 대상 또는 관리자/시스템 종목으로 의미를 좁힌다.
- `holdings`: 현재는 서버 저장 보유 정보. Public Site MVP에서는 서버 저장을 피하고 브라우저 로컬 보유 정보로 옮기는 것을 권장한다.
- `dart_corp_codes`: OpenDART 고유번호 매핑용. `corp_code`는 unique, `stock_code`는 indexed.
- `news_items`: 뉴스 원문 링크, 발행/수집 시각, 원본 payload. `canonical_url`은 unique.
- `disclosures`: 공시 접수번호, 보고서명, 원문 링크, 원본 payload. `rcept_no`는 unique.
- `analysis_results`: 요약, 감성, 중요도, 포트폴리오 영향. `target_type`은 `news` 또는 `disclosure`.
- `collection_runs`: 수집/분석 작업 실행 이력. 성공/실패와 처리 건수를 기록한다.

## Adapter Boundaries

수집기는 원문 데이터를 저장하고, 분석기는 저장된 원문을 읽어 별도 분석 결과를 만든다. 원문과 분석 결과를 분리해 모델 교체, 재분석, 수집 실패 복구를 쉽게 만든다.

어댑터 계약은 `packages/core`의 `kospi_core.contracts`에 정의한다.

- `NewsCollector`: 종목별 뉴스 원문 수집 (구현 예정: Naver News Search API)
- `DisclosureCollector`: 종목별 공시 원문 수집 (구현 예정: OpenDART)
- `Analyzer`: 원문을 감성ㆍ중요도ㆍ포트폴리오 영향으로 분류
  - `RuleBasedAnalyzer`: 외부 키 없이 키워드 규칙으로 동작 (구현 완료)
  - LLM 기반 분석기는 동일 프로토콜로 교체
- `BrokerAdapter`: NH/NAMUH 보유 종목 동기화 (구현 예정)

MVP에 추가할 어댑터:

- `DisclosureCollector`: OpenDART
- `NewsCollector`: Naver News Search API
- `Analyzer`: LLM 또는 룰 기반 분석

MVP 이후 추가할 어댑터:

- `BrokerAdapter`: NH/NAMUH 보유 종목 동기화

## API Contract To Add

실데이터 MVP에서는 mock endpoint 대신 아래 collection API를 추가한다.

```text
POST /api/collections/run
GET  /api/collections/runs
GET  /api/collections/runs/{run_id}
```

`POST /api/collections/run` 요청 후보:

```json
{
  "symbol_ids": [1, 2],
  "include_disclosures": true,
  "include_news": true,
  "analyze": true
}
```

규칙:

- `symbol_ids`가 없으면 등록된 전체 종목을 대상으로 실행한다.
- API 키가 없으면 `collection_runs.status = "failed"`와 명확한 `message`를 남긴다.
- 부분 실패가 있으면 가능한 데이터는 저장하고 `message`에 실패 요약을 남긴다.
- 응답은 실행 결과를 표현하는 `CollectionRunRead` schema를 추가해 반환한다.

Public Site MVP에서는 공개 조회 API도 필요하다.

```text
GET /api/public/symbols/search?q=삼성
GET /api/public/symbols/{code}
GET /api/public/symbols/{code}/feed
GET /api/public/feed?market=KOSPI&type=news
```

공개 API 규칙:

- 인증 없이 읽기 가능해야 한다.
- 쓰기 API는 공개 사용자에게 열지 않는다.
- rate limit 또는 캐시 정책을 둔다.
- 응답에는 개인 보유 정보가 포함되지 않는다.

## Work Queue

### MVP-01 OpenDART Corp Code Import

Status: done

Depends on: none

Goal: OpenDART `corpCode.xml`을 가져와 `dart_corp_codes`에 upsert하고, 등록 종목의 `stock_code`로 `corp_code`를 찾을 수 있게 한다.

Files:

- Add `apps/api/app/services/opendart.py`
- Update `apps/api/app/config.py`
- Update `apps/api/app/schemas.py`
- Add or update `apps/api/app/routers/collections.py`
- Update `apps/api/app/main.py`

Acceptance Criteria:

- `OPENDART_API_KEY`가 있으면 corp code import가 실행된다.
- 같은 corp code를 여러 번 import해도 중복 row가 생기지 않는다.
- 삼성전자 `005930` 같은 등록 종목 코드로 corp code를 조회할 수 있다.
- API 키가 없거나 다운로드 실패 시 실패 이유가 `collection_runs.message` 또는 API error에 남는다.

Verification:

- Unit test: ZIP/XML fixture를 사용해 import/upsert를 검증한다.
- Manual: import 후 DB의 `dart_corp_codes`에서 `stock_code = "005930"` 조회가 가능해야 한다.

### MVP-02 OpenDART Disclosure Collector

Status: done

Depends on: MVP-01

Goal: 등록 종목별 최신 공시를 OpenDART에서 수집해 `disclosures`에 저장한다.

Files:

- Update `apps/api/app/services/opendart.py`
- Update `apps/api/app/schemas.py` if run result fields are needed
- Update `apps/api/app/routers/collections.py`

Acceptance Criteria:

- 등록 종목 1개 이상에 대해 실제 공시가 `disclosures`에 저장된다.
- 같은 기간을 다시 수집해도 `rcept_no` 중복 row가 생기지 않는다.
- 수집 건수와 실패 사유가 `collection_runs`에 남는다.
- `GET /api/symbols/{symbol_id}`에서 공시가 내려오고 웹 피드에 표시될 수 있다.

Verification:

- Unit test: OpenDART response fixture로 insert/dedupe를 검증한다.
- Manual: 종목 등록 후 collection run 실행, `/api/symbols/{id}`에서 `disclosures` 확인.

### MVP-03 Naver News Collector

Status: done

Depends on: none

Goal: 등록 종목별 최신 뉴스를 Naver News Search API에서 수집해 `news_items`에 저장한다.

Files:

- Add `apps/api/app/services/naver_news.py`
- Update `apps/api/app/config.py`
- Update `apps/api/app/routers/collections.py`

Acceptance Criteria:

- 등록 종목 1개 이상에 대해 실제 뉴스가 `news_items`에 저장된다.
- 같은 뉴스를 다시 수집해도 `canonical_url` 중복 row가 생기지 않는다.
- API 키가 없거나 호출 실패 시 실패 이유가 남는다.
- `GET /api/symbols/{symbol_id}`에서 뉴스가 내려오고 웹 피드에 표시될 수 있다.

Verification:

- Unit test: Naver response fixture로 title cleanup, datetime parsing, dedupe를 검증한다.
- Manual: 종목 등록 후 collection run 실행, `/api/symbols/{id}`에서 `news_items` 확인.

### MVP-04 Analyzer Adapter

Status: done

Depends on: MVP-02, MVP-03

Goal: 수집된 뉴스/공시 원문을 읽어 `analysis_results`에 요약, 감성, 중요도, 포트폴리오 영향을 저장한다.

Files:

- Add `apps/api/app/services/analyzer.py`
- Update `apps/api/app/routers/collections.py`

Acceptance Criteria:

- 분석 대상 뉴스/공시마다 최신 분석 결과가 생성된다.
- `sentiment`는 `positive`, `negative`, `neutral` 중 하나다.
- `importance`는 1에서 5 사이 정수다.
- 웹 피드에서 AI 요약, 포트폴리오 영향, 중요도가 mock 없이 표시된다.

Verification:

- Unit test: 뉴스/공시 샘플별 분석 결과 shape와 range를 검증한다.
- Manual: collection run 후 `/api/symbols/{id}`에서 `analysis`가 null이 아니어야 한다.

### MVP-05 Collection Run Service And API

Status: done

Depends on: MVP-01, MVP-02, MVP-03, MVP-04

Goal: corp code import, 공시 수집, 뉴스 수집, 분석을 하나의 실행 단위로 묶고 `collection_runs`에 결과를 남긴다.

Files:

- Add `apps/api/app/services/collections.py`
- Add `apps/api/app/routers/collections.py`
- Update `apps/api/app/schemas.py`
- Update `apps/api/app/main.py`

Acceptance Criteria:

- `POST /api/collections/run`으로 전체 등록 종목 수집/분석을 실행할 수 있다.
- `GET /api/collections/runs`에서 최근 실행 이력을 볼 수 있다.
- `GET /api/collections/runs/{run_id}`에서 단일 실행 결과를 볼 수 있다.
- 실패해도 `finished_at`과 `message`가 남는다.

Verification:

- API test: collection run 생성, 목록 조회, 상세 조회를 검증한다.
- Manual: API 호출 후 `collection_runs` row와 웹 데이터 갱신을 확인한다.

### MVP-06 Web Real Collection UI

Status: done

Depends on: MVP-05

Goal: 프론트의 mock 수집 호출을 실제 collection API로 바꾸고 수집 상태를 사용자에게 보여준다.

Files:

- Update `apps/web/src/api.ts`
- Update `apps/web/src/types.ts`
- Update `apps/web/src/App.tsx`
- Update `apps/web/src/styles.css` only if needed

Acceptance Criteria:

- 웹의 수집 버튼이 mock endpoint가 아니라 실제 collection endpoint를 호출한다.
- 수집 실패 시 화면에 실패 메시지가 표시된다.
- 수집 성공 후 대시보드와 통합 피드가 실제 `news_items`, `disclosures`, `analysis_results`를 보여준다.
- 빈 데이터, 수집 중, 실패, 성공 상태가 구분된다.

Verification:

- `npm run web:build` 성공
- Manual: API 서버 실행 후 웹에서 수집 버튼 클릭, 네트워크 요청이 `/api/collections/run`인지 확인

### MVP-07 Scheduler

Status: done

Depends on: MVP-05

Goal: 주기적으로 collection run을 실행하는 worker entrypoint를 만든다.

Files:

- Update `workers/scheduler.py`
- Update `workers/README.md`

Acceptance Criteria:

- worker를 실행하면 주기적으로 collection run이 생성된다.
- 실행 실패가 worker 프로세스를 조용히 죽이지 않고 로그와 `collection_runs.message`에 남는다.
- API 서버 없이도 같은 service 로직을 재사용할 수 있다.

Verification:

- Manual: worker 실행 후 `collection_runs`가 주기적으로 쌓이는지 확인한다.
- Unit test: running run이 있을 때 skip 정책을 검증한다.

### MVP-08 Tests And Hardening

Status: done

Depends on: MVP-01 through MVP-07

Goal: 실데이터 MVP를 반복 개발할 수 있게 최소 자동 검증을 만든다.

Files:

- Add API test structure under `apps/api/tests` or `tests`
- Update `apps/api/requirements.txt` with test dependencies if needed
- Consider adding root scripts for API tests
- Keep `npm run web:build` as frontend verification

Acceptance Criteria:

- API test command가 문서화되어 있다.
- corp code import, disclosure collector, news collector, analyzer, collection API의 핵심 path가 테스트된다.
- `npm run web:build`가 성공한다.

Verification:

- API test command 성공
- `npm run web:build` 성공

### MVP-09 Public User Data Boundary

Status: done

Depends on: MVP-06

Goal: 공개 사용자에게 서버 전역 portfolio CRUD를 노출하지 않도록 데이터 경계를 정리한다.

Files:

- Update `apps/web/src/App.tsx`
- Update `apps/web/src/api.ts`
- Update `apps/web/src/types.ts`
- Add browser storage helper if useful
- Add public read-only routers if needed

Acceptance Criteria:

- 일반 사용자가 추가한 관심종목/보유정보가 다른 사용자에게 보이지 않는다.
- 공개 읽기 API는 뉴스/공시/분석 같은 공개 데이터만 반환한다.
- 서버 쓰기 API는 개발/관리 용도로만 사용되거나 공개 UI에서 제거된다.
- 브라우저 로컬 관심종목을 비워도 공개 피드 탐색은 가능하다.

Verification:

- Manual: 브라우저 두 개에서 서로 다른 관심종목 상태가 분리되는지 확인한다.
- `npm run web:build` 성공

### MVP-10 Public Read UX And SEO

Status: not-started

Depends on: MVP-09

Goal: 일반 사용자가 처음 접속해도 종목 검색, 공개 피드, 종목 상세를 이해하고 탐색할 수 있게 만든다.

Files:

- Update `apps/web/src/App.tsx`
- Update `apps/web/src/styles.css`
- Update `apps/web/index.html`
- Add sitemap/robots generation if static hosting supports it

Acceptance Criteria:

- 첫 화면에서 공개 시장 피드나 대표 종목 피드를 볼 수 있다.
- 종목 검색에서 상세 페이지 또는 상세 패널로 이동할 수 있다.
- title, description, Open Graph 기본 metadata가 있다.
- robots/sitemap 정책이 준비되어 있다.
- 투자 조언이 아니라 정보 요약 서비스라는 disclaimer가 화면 또는 footer에 있다.

Verification:

- `npm run web:build` 성공
- Manual: 빈 브라우저 상태에서 도메인 첫 접속 플로우를 점검한다.

### MVP-11 Deployment, Domain, HTTPS

Status: not-started

Depends on: MVP-08, MVP-10

Goal: 사용자가 실제 도메인으로 접속할 수 있는 공개 환경을 만든다.

Files:

- Add deployment docs under `docs/`
- Add production env example if needed
- Update CORS and API base URL configuration
- Add deployment config for chosen platform if needed

Acceptance Criteria:

- 웹 앱이 공개 URL에서 열린다.
- API가 공개 환경에서 접근 가능하다.
- HTTPS가 적용되어 있다.
- `CORS_ORIGINS`가 실제 도메인 기준으로 설정된다.
- DB 파일 또는 managed DB가 재배포 때 사라지지 않는다.
- health endpoint가 공개 환경에서 동작한다.

Verification:

- Manual: 실제 도메인에서 웹 접속, API health, 주요 API 호출 확인
- `npm run web:build` 성공

### MVP-12 Public Operations And Monetization Readiness

Status: not-started

Depends on: MVP-11

Goal: 공개 사이트 운영과 향후 광고 수익화를 막지 않는 최소 준비를 한다.

Files:

- Update public UI/footer/policy copy
- Add analytics hook/config if selected
- Add docs for operations checklist

Acceptance Criteria:

- 기본 analytics를 붙일 위치가 정해져 있다.
- 광고 슬롯을 넣을 수 있는 주요 레이아웃 위치가 정해져 있다.
- 개인정보/쿠키/광고 정책 문서 초안 위치가 정해져 있다.
- API rate limit 또는 cache 전략이 문서화되어 있다.
- OpenDART/Naver API 호출량을 보호하는 캐시/스케줄 중심 구조가 유지된다.

Verification:

- Manual: 공개 페이지에서 footer/policy/disclaimer 확인
- Operations checklist review

## Recommended Implementation Order

1. MVP-01 OpenDART Corp Code Import
2. MVP-02 OpenDART Disclosure Collector
3. MVP-03 Naver News Collector
4. MVP-04 Analyzer Adapter
5. MVP-05 Collection Run Service And API
6. MVP-06 Web Real Collection UI
7. MVP-07 Scheduler
8. MVP-08 Tests And Hardening
9. MVP-09 Public User Data Boundary
10. MVP-10 Public Read UX And SEO
11. MVP-11 Deployment, Domain, HTTPS
12. MVP-12 Public Operations And Monetization Readiness

MVP-08은 마지막 티켓처럼 보이지만, 각 collector를 만들 때 fixture 기반 단위 테스트를 함께 추가하는 편이 좋다.

## Completion Checklist

Real Data Engine:

- [ ] `dart_corp_codes`에 실제 OpenDART corp code가 들어간다.
- [ ] 등록 종목의 `disclosures`가 실제 OpenDART 데이터로 채워진다.
- [ ] 등록 종목의 `news_items`가 실제 Naver 뉴스 데이터로 채워진다.
- [ ] `analysis_results`가 mock 없이 생성된다.
- [ ] `collection_runs`에 성공/실패/처리 건수가 남는다.
- [ ] 웹 수집 버튼이 `/api/collections/run`을 호출한다.
- [ ] 웹 대시보드와 통합 피드가 실제 수집 데이터로 동작한다.
- [ ] `npm run web:build`가 성공한다.
- [ ] API 핵심 path 테스트가 성공한다.

Public Site:

- [ ] 일반 사용자가 실제 도메인으로 접속할 수 있다.
- [ ] HTTPS가 적용되어 있다.
- [ ] 공개 사용자의 관심종목/보유정보가 서버 전역 데이터로 섞이지 않는다.
- [ ] 가입 없이 공개 종목 검색과 피드 탐색이 가능하다.
- [ ] 기본 metadata, sitemap, robots 정책이 준비되어 있다.
- [ ] disclaimer와 정책 문서 위치가 있다.
- [ ] analytics와 광고 슬롯을 추가할 구조가 준비되어 있다.
