# MVP Architecture

## Goal

초기 MVP는 계좌 연동 없이 사용자가 직접 등록한 종목을 중심으로 동작한다. 종목 관리와 대시보드가 먼저 안정적으로 돌아가야 이후 OpenDART, Naver News, NH/NAMUH 계좌 어댑터를 붙일 수 있다.

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

## Domain Tables

- `symbols`: 시장, 코드, 종목명, 메모
- `holdings`: 수량, 평균단가, 평가금액, 포트폴리오 비중
- `dart_corp_codes`: OpenDART 고유번호 매핑용
- `news_items`: 뉴스 원문 링크, 발행/수집 시각, 원본 payload
- `disclosures`: 공시 접수번호, 보고서명, 원문 링크, 원본 payload
- `analysis_results`: 요약, 감성, 중요도, 포트폴리오 영향
- `collection_runs`: 수집/분석 작업 실행 이력

## Adapter Boundaries

수집기는 원문 데이터를 저장하고, 분석기는 저장된 원문을 읽어 별도 분석 결과를 만든다. 원문과 분석 결과를 분리해 모델 교체, 재분석, 수집 실패 복구를 쉽게 만든다.

어댑터 계약은 `packages/core`의 `kospi_core.contracts`에 정의한다.

- `NewsCollector`: 종목별 뉴스 원문 수집 (구현 예정: Naver News Search API)
- `DisclosureCollector`: 종목별 공시 원문 수집 (구현 예정: OpenDART)
- `Analyzer`: 원문을 감성ㆍ중요도ㆍ포트폴리오 영향으로 분류
  - `RuleBasedAnalyzer`: 외부 키 없이 키워드 규칙으로 동작 (구현 완료)
  - LLM 기반 분석기는 동일 프로토콜로 교체
- `BrokerAdapter`: NH/NAMUH 보유 종목 동기화 (구현 예정)
