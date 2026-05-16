# workers

`scheduler.py`는 통합 수집 파이프라인을 주기적으로 실행하는 worker다. API 서버와 동일한 `app.services.collections` 로직을 재사용하므로 API 서버가 떠 있지 않아도 동작한다.

## 실행

```bash
npm run worker
```

직접 실행하려면:

```bash
PYTHONPATH=apps/api:packages/core .venv/bin/python workers/scheduler.py
```

## 동작

- `COLLECTION_INTERVAL_SECONDS`(기본 600초)마다 collection run을 한 번 실행한다.
- 이미 `running` 상태의 collection run이 있으면 해당 주기는 건너뛴다.
- 한 주기 실행이 실패해도 worker 프로세스는 종료되지 않으며, 실패 사유는 로그와 `collection_runs.message`에 남는다.
- 수집 대상과 API 키는 API 서버와 동일하게 `.env`/환경 변수 설정을 따른다.
