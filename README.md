# Kospi Portfolio Research

수동 등록한 관심/보유 종목에 대해 뉴스와 공시를 수집하고, 웹에서 최신 투자 이슈를 확인하는 개인 포트폴리오 리서치 대시보드입니다.

실데이터 수집·분석 엔진이 구현되어 있습니다.

- FastAPI 백엔드 + SQLite 도메인 모델
- 종목 등록/수정/삭제/조회 API
- OpenDART corp code import, OpenDART 공시 수집, Naver 뉴스 수집
- 룰 기반 분석기(요약·감성·중요도·포트폴리오 영향)
- corp code import·수집·분석을 묶는 통합 collection run API와 주기 실행 worker
- 실제 수집 데이터로 동작하는 React 대시보드

다음 단계는 일반 사용자가 도메인으로 접속하는 공개 사이트(MVP-09~12)입니다. 진행 현황은 `docs/mvp-architecture.md`를 참고하세요.

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

웹은 Google OAuth 로그인 후 사용할 수 있습니다. Google Cloud Console에서 OAuth
웹 클라이언트를 만들고 redirect URI를
`http://127.0.0.1:8000/api/auth/google/callback`로 등록한 뒤 `.env`에
`GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`을 설정합니다.

웹의 수집 버튼은 `/api/collections/run`을 호출해 등록 종목의 공시·뉴스를 수집하고 분석합니다. OpenDART/Naver API 키는 `.env`에 설정합니다(`.env.example` 참고). 주기 수집은 `npm run worker`로 실행합니다.

## 테스트

API/수집기/분석기 테스트는 Python 표준 라이브러리 `unittest` 기반이라 추가 설치가 필요 없습니다.

```bash
npm run api:test     # API·수집기·분석기 단위 테스트
npm run web:build    # 프론트엔드 타입 체크 및 빌드
npm run verify       # 위 둘을 한 번에 실행
```
