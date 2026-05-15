# workers

스케줄 기반 수집과 분석 작업을 둘 자리입니다.

초기 실행 순서:

1. 종목 등록과 대시보드 검증
2. OpenDART `corp_code` 매핑 import
3. 공시 수집 Worker
4. 뉴스 수집 Worker
5. 분석 Worker
6. 스케줄러 연결
