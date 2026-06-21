# 운영 가이드

공개 사이트 운영과 향후 광고 수익화를 막지 않기 위한 최소 준비 사항이다.

## 외부 API 호출량 보호

OpenDART와 Naver 검색 API는 호출 한도가 있다. 호출량이 웹 트래픽이 아니라
수집 주기에만 비례하도록 설계돼 있다.

- 웹은 서버 DB(`/api/symbols`, `/api/symbols/{id}` 등)만 읽는다. 방문자가
  늘어도 외부 API를 직접 호출하지 않는다.
- 외부 API 호출은 수집 실행(`POST /api/collections/run` 또는 worker)에서만
  발생한다. 호출량은 `COLLECTION_INTERVAL_SECONDS`(worker 주기)로 통제한다.
- OpenDART corpCode import는 ~2MB 아카이브를 받으므로 자주 실행하지 않는다.
  (`import_corp_codes` 옵션 기본 off — 종목 추가/주기적 갱신 시에만 실행.)
- 수집한 공시·뉴스는 `rcept_no`/`canonical_url` 기준으로 dedupe 되어 재수집
  해도 중복 저장·재분석이 일어나지 않는다.

## rate limit · 캐시 전략

현재 공개 읽기 API에는 별도 rate limit이 없다. 트래픽이 늘면 아래를 우선
도입한다.

- API 앞단(리버스 프록시/CDN)에서 `GET /api/symbols*` 응답을 단기 캐시.
- 또는 FastAPI 미들웨어로 IP 기준 rate limit.

웹이 외부 API가 아닌 수집 DB만 읽는 구조 자체가 1차 방어선이므로, 위 항목은
트래픽 규모에 따라 추가한다.

## analytics

analytics 스니펫 위치는 `apps/web/index.html`의 `<head>` 주석으로 표시돼
있다. 제공자를 선택하면 그 위치에 측정 스니펫을 넣는다.

## 광고 슬롯

레이아웃의 광고 슬롯은 `AdSlot` 컴포넌트(`apps/web/src/App.tsx`)로 표시한다.
현재 `page-bottom` 슬롯이 본문과 footer 사이에 예약돼 있으며, 비어 있을 때는
공간을 차지하지 않는다. 광고 네트워크 연동은 MVP 이후 작업이다.

## 데이터베이스 백업·복구

수개월치 공시·뉴스·AI 요약·데일리 리포트가 단일 SQLite 파일
(`data/kospi.db`)에 쌓인다. 영속 볼륨은 재배포 보존일 뿐 백업이 아니다 —
파일 손상·실수 삭제 시 전량 복구가 불가능하므로 별도 백업을 둔다.

### 백업

`scripts/backup_db.sh`가 SQLite 온라인 백업 API(`.backup`)로 일관된 스냅샷을
만든다. worker/API가 쓰는 중에도 안전하며, 무결성 검사(`PRAGMA
integrity_check`) 후 gzip 압축하고 오래된 아카이브를 정리한다.

```bash
# 수동 실행 — data/backups/kospi-YYYYMMDD-HHMMSS.db.gz 생성, 최신 14개 유지
scripts/backup_db.sh

# 경로/보관 개수 커스터마이즈 (인자 또는 환경변수)
scripts/backup_db.sh /path/to/kospi.db /path/to/backups 30
KOSPI_BACKUP_KEEP=30 scripts/backup_db.sh
```

매일 자동 백업은 worker와 같은 launchd로 등록한다. 예시
(`~/Library/LaunchAgents/com.kospi.backup.plist`, 매일 04:00):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.kospi.backup</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>/Users/star001/projects/kospi/scripts/backup_db.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>4</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>/Users/star001/projects/kospi/data/backup.log</string>
  <key>StandardErrorPath</key><string>/Users/star001/projects/kospi/data/backup.log</string>
</dict></plist>
```

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.kospi.backup.plist
launchctl kickstart -k gui/$(id -u)/com.kospi.backup   # 즉시 1회 실행해 확인
```

리눅스 호스트면 cron 으로 동일하게: `0 4 * * * /…/scripts/backup_db.sh`.

### 복구

```bash
# 1) worker/API 중지 (launchd면 bootout)
launchctl bootout gui/$(id -u)/com.kospi.worker

# 2) 백업 해제 후 제자리 복원 (WAL 사이드카는 함께 제거)
gunzip -c data/backups/kospi-YYYYMMDD-HHMMSS.db.gz > data/kospi.db
rm -f data/kospi.db-wal data/kospi.db-shm

# 3) 무결성 확인 후 worker/API 재기동
sqlite3 data/kospi.db 'PRAGMA integrity_check;'
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.kospi.worker.plist
```

백업은 `data/backups/`에 쌓이며 `.gitignore`로 제외된다. 원격지(다른 디스크/
오브젝트 스토리지)로도 주기적으로 복제하면 디스크 장애까지 대비된다.

## 정책 문서

개인정보·쿠키·광고 정책 초안은 `docs/policies.md`에 있다. 공개 정책 페이지로
게시하기 전 법무 검토가 필요하다.

## 운영 체크리스트

- [ ] worker가 동작하며 `GET /api/collections/runs`에 실행 이력이 쌓인다.
- [ ] 최근 collection run의 `status`가 `failed`면 `message`로 원인을 확인한다.
- [ ] OpenDART/Naver API 키 사용량이 한도 내인지 주기적으로 점검한다.
- [ ] 재배포 후 DB(영속 볼륨/managed DB)와 수집 이력이 보존됐는지 확인한다.
- [ ] 일일 백업(`com.kospi.backup`)이 돌며 `data/backups/`에 최신 아카이브가 쌓인다.
- [ ] `/api/health`가 정상 응답하는지 모니터링한다.
- [ ] analytics·광고 도입 시 `docs/policies.md`를 갱신한다.
