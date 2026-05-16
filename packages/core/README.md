# packages/core

수집기와 분석기가 공유하는 도메인 계약을 두는 패키지입니다. 프레임워크·DB 의존성이 없어 FastAPI 앱과 워커가 함께 import 합니다.

## kospi_core

- `contracts.py`: 값 객체(`SymbolRef`, `NewsDraft`, `DisclosureDraft`, `AnalysisSubject`, `AnalysisDraft`)와 어댑터 인터페이스(`NewsCollector`, `DisclosureCollector`, `Analyzer`)
- `analyzer.py`: 외부 키 없이 한국어 키워드 규칙으로 동작하는 `RuleBasedAnalyzer`

## 사용

`packages/core`를 `PYTHONPATH`에 추가하면 import 할 수 있습니다. `npm run api:dev`에는 이미 반영돼 있습니다.

```python
from kospi_core import AnalysisSubject, RuleBasedAnalyzer

draft = RuleBasedAnalyzer().analyze(
    AnalysisSubject(kind="news", symbol_name="삼성전자", title="삼성전자 신규 수주 확대")
)
```

LLM 기반 분석기는 `Analyzer` 프로토콜을 동일하게 구현해 교체합니다.
