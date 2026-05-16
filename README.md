# Kospi Portfolio Research

수동 등록한 관심/보유 종목에 대해 뉴스와 공시를 수집하고, 웹에서 최신 투자 이슈를 확인하는 개인 포트폴리오 리서치 대시보드입니다.

현재 구현 범위는 실데이터 MVP 이전의 UI/API 검증 단계입니다.

- FastAPI 백엔드 스캐폴딩
- SQLite 기반 도메인 모델
- 종목 등록/수정/삭제/조회 API
- React 대시보드
- 외부 API 없이 화면 흐름을 확인하는 데모 데이터 생성

MVP 완료 기준은 등록 종목에 대해 실제 OpenDART 공시와 Naver 뉴스 검색 결과를 수집하고, 분석 결과를 웹에서 확인할 수 있는 상태입니다.

## 구조

```text
apps/api          FastAPI backend
apps/web          React dashboard
packages/core     Shared domain placeholder
workers           Scheduler and collector placeholder
docs              Architecture notes
data              Local SQLite database
```

## 실행

Python 3.10 이상을 권장합니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r apps/api/requirements.txt
npm install
```

이 로컬 머신처럼 venv의 `ensurepip`가 실패하는 환경에서는 아래 방식으로도 실행할 수 있습니다.

```bash
python3 -m pip install --target .python-deps -r apps/api/requirements.txt
npm install
```

터미널 1:

```bash
npm run api:dev
```

터미널 2:

```bash
npm run web:dev
```

기본 주소:

- API: `http://127.0.0.1:8000`
- Web: `http://127.0.0.1:5173`
- Health: `http://127.0.0.1:8000/api/health`

웹에서 수집 버튼을 누르면 현재는 샘플 뉴스, 공시, 분석 결과가 생성됩니다. 실데이터 MVP에서는 이 흐름을 OpenDART/Naver 수집과 분석 실행으로 대체합니다.

## 실데이터 MVP 잔여 작업

1. OpenDART `corp_code` import
2. OpenDART 공시 수집기
3. Naver 뉴스 검색 수집기
4. 분석기 어댑터 연결 (룰 기반 분석기는 `packages/core`에 구현됨, LLM 기반 분석기는 이후 동일 계약으로 교체)
5. 수동 수집 API와 Worker 실행 이력
6. 주기 실행 스케줄러
7. 웹 수집 UI를 실제 수집 상태로 전환
8. API/수집기/분석기 최소 테스트
