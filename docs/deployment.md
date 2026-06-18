# 배포 가이드

KOSPI Reporter를 공개 도메인에 배포하는 절차다. 구성 요소는 세 가지다.

- **웹**: 정적 빌드 산출물(`apps/web/dist/`) — 정적 호스팅에 올린다.
- **API**: FastAPI 컨테이너 — Python 컨테이너 플랫폼에 올린다.
- **수집 worker**: API와 같은 이미지로 스케줄러를 실행한다.

## 1. 웹 배포

`VITE_API_BASE_URL`은 빌드 시점에 주입되므로, 공개 API 주소를 지정해 빌드한다.

```bash
VITE_API_BASE_URL=https://api.your-domain.example npm run web:build
```

`apps/web/dist/`를 HTTPS를 지원하는 정적 호스팅(Cloudflare Pages, Netlify,
Vercel, S3+CloudFront 등)에 올린다. 산출물에는 `robots.txt`와 `sitemap.xml`이
포함된다 — 배포 도메인이 확정되면 두 파일(`apps/web/public/`)의 placeholder
도메인을 실제 도메인으로 갱신한다.

## 2. API 배포

루트의 `Dockerfile`로 이미지를 만든다.

```bash
docker build -t kospi-api .
```

컨테이너 플랫폼(Render, Railway, Fly.io, Cloud Run 등)에 배포하며 아래를
설정한다.

- **환경 변수**: `.env.production.example` 참고. 최소 `CORS_ORIGINS`(웹 도메인),
  `OPENDART_API_KEY`, `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`.
- **포트**: 컨테이너는 `$PORT`(기본 8000)에서 listen 한다.
- **health check**: `GET /api/health` — `{"status":"ok"}`를 반환한다.
- **영속 볼륨**: SQLite DB(`/app/data/kospi.db`)가 재배포 때 사라지지 않도록
  `/app/data`에 영속 볼륨을 마운트한다.

### managed DB 사용 시

영속 볼륨 대신 managed 데이터베이스를 쓰려면 `DATABASE_URL`을 지정한다(예:
`postgresql+psycopg2://...`). 이 경우 `apps/api/requirements.txt`에 해당
드라이버(`psycopg2-binary` 등)를 추가해야 한다.

## 3. 수집 worker

API와 같은 이미지에서 명령만 바꿔 실행한다.

```bash
docker run --env-file .env <image> python workers/scheduler.py
```

worker는 API와 같은 DB(영속 볼륨 또는 `DATABASE_URL`)를 공유해야 한다.
`COLLECTION_INTERVAL_SECONDS`로 수집 주기를 조정한다.

## 4. HTTPS · 도메인

- 웹: 정적 호스팅이 제공하는 자동 HTTPS를 사용한다.
- API: 플랫폼의 관리형 TLS 또는 앞단 리버스 프록시로 HTTPS를 적용한다.
- API는 별도 서브도메인(`api.your-domain.example`)에 두는 것을 권장한다.

## 5. CORS

`CORS_ORIGINS`는 쉼표로 구분된 허용 origin 목록이다. 공개 웹 도메인을 정확히
지정한다(와일드카드 금지).

```
CORS_ORIGINS=https://your-domain.example
```

## 6. 접근 제어 (로그인 허용 목록)

공개 사이트는 Google 로그인을 거치지만, 기본 상태에서는 Google 계정이 있는
누구나 로그인할 수 있다. 특정 사용자에게만 열려면 `AUTH_ALLOWED_EMAILS`에
허용할 이메일을 쉼표로 나열한다.

```
AUTH_ALLOWED_EMAILS=alice@example.com,bob@example.com
```

- 비워 두면 모든 Google 계정이 로그인할 수 있다(로컬 개발 기본값) — 공개
  배포 전에는 반드시 채운다.
- 목록에 없는 계정은 로그인 단계에서 차단되고 `?auth_error=not_allowed`로
  웹에 돌아온다.
- 로그인에는 Google OAuth가 필요하다. `GOOGLE_OAUTH_CLIENT_ID/SECRET`과
  공개 콜백 주소(`GOOGLE_OAUTH_REDIRECT_URI`)를 설정하고, HTTPS에서는
  `AUTH_COOKIE_SECURE=true`로 둔다.
- 모든 데이터 API는 GET을 포함해 로그인을 요구한다(deny-by-default). 세션
  없이 호출하면 401이다.

## 배포 체크리스트

- [ ] `VITE_API_BASE_URL`을 공개 API 주소로 지정해 웹을 빌드했다.
- [ ] 웹이 HTTPS 공개 URL에서 열린다.
- [ ] API 컨테이너가 공개 환경에서 실행되고 `/api/health`가 응답한다.
- [ ] `CORS_ORIGINS`가 실제 웹 도메인으로 설정됐다.
- [ ] Google OAuth 키와 공개 콜백 URL을 설정하고 `AUTH_COOKIE_SECURE=true`로 뒀다.
- [ ] `AUTH_ALLOWED_EMAILS`에 허용 사용자를 지정했다(공개 시 필수).
- [ ] DB가 영속 볼륨 또는 managed DB에 있어 재배포 때 보존된다.
- [ ] `robots.txt`/`sitemap.xml`의 도메인을 실제 도메인으로 갱신했다.
- [ ] 수집 worker가 동작하고 `collection_runs`가 쌓인다.
