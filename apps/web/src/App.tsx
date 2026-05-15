import {
  Activity,
  BarChart3,
  Bell,
  Check,
  DatabaseZap,
  ExternalLink,
  FileText,
  Newspaper,
  Plus,
  RefreshCw,
  Save,
  Search,
  Trash2,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { api, SymbolPayload } from "./api";
import type {
  AnalyzedDisclosure,
  AnalyzedNewsItem,
  BriefItem,
  PortfolioBrief,
  Sentiment,
  SymbolDetail,
  SymbolRecord,
} from "./types";

type FormState = {
  market: string;
  code: string;
  name: string;
  memo: string;
  quantity: string;
  average_cost: string;
  market_value: string;
  portfolio_weight: string;
};

const blankForm: FormState = {
  market: "KOSPI",
  code: "",
  name: "",
  memo: "",
  quantity: "",
  average_cost: "",
  market_value: "",
  portfolio_weight: "",
};

function numberOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

function payloadFromForm(form: FormState): SymbolPayload {
  const holding = {
    quantity: numberOrNull(form.quantity),
    average_cost: numberOrNull(form.average_cost),
    market_value: numberOrNull(form.market_value),
    portfolio_weight: numberOrNull(form.portfolio_weight),
  };
  const hasHolding = Object.values(holding).some((value) => value !== null);
  return {
    market: form.market.trim().toUpperCase(),
    code: form.code.trim().toUpperCase(),
    name: form.name.trim(),
    memo: form.memo.trim() || null,
    holding: hasHolding ? holding : null,
  };
}

function formFromSymbol(symbol: SymbolRecord): FormState {
  return {
    market: symbol.market,
    code: symbol.code,
    name: symbol.name,
    memo: symbol.memo ?? "",
    quantity: symbol.holding?.quantity?.toString() ?? "",
    average_cost: symbol.holding?.average_cost?.toString() ?? "",
    market_value: symbol.holding?.market_value?.toString() ?? "",
    portfolio_weight: symbol.holding?.portfolio_weight?.toString() ?? "",
  };
}

function formatDate(value: string | null): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatMoney(value: number | null | undefined): string {
  if (!value) return "-";
  return new Intl.NumberFormat("ko-KR", {
    maximumFractionDigits: 0,
  }).format(value);
}

function sentimentLabel(sentiment: Sentiment | null | undefined): string {
  if (sentiment === "positive") return "긍정";
  if (sentiment === "negative") return "부정";
  if (sentiment === "neutral") return "중립";
  return "미분석";
}

function App() {
  const [symbols, setSymbols] = useState<SymbolRecord[]>([]);
  const [brief, setBrief] = useState<PortfolioBrief | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<SymbolDetail | null>(null);
  const [createForm, setCreateForm] = useState<FormState>(blankForm);
  const [editForm, setEditForm] = useState<FormState>(blankForm);
  const [isLoading, setIsLoading] = useState(true);
  const [isBusy, setIsBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectedSymbol = useMemo(
    () => symbols.find((symbol) => symbol.id === selectedId) ?? null,
    [selectedId, symbols],
  );

  async function refresh(nextSelectedId = selectedId) {
    const [nextBrief, nextSymbols] = await Promise.all([api.getBrief(), api.listSymbols()]);
    setBrief(nextBrief);
    setSymbols(nextSymbols);

    const fallbackId = nextSelectedId ?? nextSymbols[0]?.id ?? null;
    setSelectedId(fallbackId);
    if (fallbackId) {
      const nextDetail = await api.getSymbol(fallbackId);
      setDetail(nextDetail);
      setEditForm(formFromSymbol(nextDetail));
    } else {
      setDetail(null);
      setEditForm(blankForm);
    }
  }

  useEffect(() => {
    refresh()
      .catch((err: Error) => setError(err.message))
      .finally(() => setIsLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    api
      .getSymbol(selectedId)
      .then((nextDetail) => {
        setDetail(nextDetail);
        setEditForm(formFromSymbol(nextDetail));
      })
      .catch((err: Error) => setError(err.message));
  }, [selectedId]);

  async function runAction(action: () => Promise<void>, success: string) {
    setIsBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
      setNotice(success);
    } catch (err) {
      setError(err instanceof Error ? err.message : "작업에 실패했습니다.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    await runAction(async () => {
      const created = await api.createSymbol(payloadFromForm(createForm));
      setCreateForm(blankForm);
      await refresh(created.id);
    }, "종목을 등록했습니다.");
  }

  async function handleCreateLookup() {
    await runAction(async () => {
      const query = createForm.code.trim() || createForm.name.trim();
      if (!query) {
        throw new Error("종목코드나 종목명 중 하나를 입력해 주세요.");
      }

      const matches = await api.lookupSymbols(query, createForm.market);
      if (!matches.length) {
        throw new Error("검색 결과가 없습니다.");
      }

      const normalizedCode = createForm.code.trim().toUpperCase();
      const normalizedName = createForm.name.trim().toLocaleLowerCase("ko-KR");
      const exactMatches = matches.filter(
        (match) =>
          match.code === normalizedCode ||
          match.name.toLocaleLowerCase("ko-KR") === normalizedName,
      );

      if (!exactMatches.length && matches.length > 1) {
        throw new Error(
          `검색 결과가 여러 개입니다: ${matches
            .slice(0, 3)
            .map((match) => `${match.name}(${match.code})`)
            .join(", ")}`,
        );
      }

      const match = exactMatches[0] ?? matches[0];
      setCreateForm({
        ...createForm,
        market: match.market,
        code: match.code,
        name: match.name,
      });
    }, "종목 정보를 채웠습니다.");
  }

  async function handleSave(event: FormEvent) {
    event.preventDefault();
    if (!selectedId) return;
    await runAction(async () => {
      await api.updateSymbol(selectedId, payloadFromForm(editForm));
      await refresh(selectedId);
    }, "종목 정보를 저장했습니다.");
  }

  async function handleDelete() {
    if (!selectedId) return;
    await runAction(async () => {
      await api.deleteSymbol(selectedId);
      await refresh(null);
    }, "종목을 삭제했습니다.");
  }

  async function handleSeed() {
    await runAction(async () => {
      await api.seedDemo();
      await refresh();
    }, "데모 데이터를 불러왔습니다.");
  }

  async function handleMockActivity() {
    if (!selectedId) return;
    await runAction(async () => {
      await api.createMockActivity(selectedId);
      await refresh(selectedId);
    }, "샘플 이슈를 갱신했습니다.");
  }

  return (
    <div className="appShell">
      <header className="topbar">
        <div className="brandBlock">
          <div className="brandMark">
            <BarChart3 size={20} />
          </div>
          <div>
            <strong>Portfolio Research</strong>
            <span>Watchlist intelligence</span>
          </div>
        </div>
        <div className="topbarActions">
          <button className="iconButton" onClick={() => refresh()} title="새로고침">
            <RefreshCw size={18} />
          </button>
          <button className="iconButton" title="알림">
            <Bell size={18} />
          </button>
        </div>
      </header>

      <div className="workspace">
        <aside className="sidebar">
          <section className="toolPanel">
            <div className="sectionHeader">
              <h2>관심 종목</h2>
              <button className="compactButton" onClick={handleSeed} disabled={isBusy}>
                <DatabaseZap size={15} />
                데모
              </button>
            </div>
            <div className="watchlist">
              {symbols.map((symbol) => (
                <button
                  key={symbol.id}
                  className={`watchRow ${symbol.id === selectedId ? "active" : ""}`}
                  onClick={() => setSelectedId(symbol.id)}
                >
                  <span className="ticker">{symbol.code}</span>
                  <span className="watchName">{symbol.name}</span>
                  <span className="marketPill">{symbol.market}</span>
                </button>
              ))}
              {!symbols.length && !isLoading && (
                <div className="emptyState">등록된 종목이 없습니다.</div>
              )}
            </div>
          </section>

          <section className="toolPanel">
            <div className="sectionHeader">
              <h2>종목 등록</h2>
              <Plus size={17} />
            </div>
            <SymbolForm
              form={createForm}
              onChange={setCreateForm}
              onSubmit={handleCreate}
              submitLabel="등록"
              submitIcon={<Plus size={16} />}
              disabled={isBusy}
              allowPartialIdentity
              onLookup={handleCreateLookup}
            />
          </section>
        </aside>

        <main className="mainContent">
          <div className="statusLine">
            <span>{isLoading ? "불러오는 중" : "준비됨"}</span>
            {notice && <span className="notice">{notice}</span>}
            {error && <span className="error">{error}</span>}
          </div>

          <section className="summaryStrip">
            <Metric
              icon={<Search size={18} />}
              label="등록 종목"
              value={brief?.total_symbols.toString() ?? "0"}
            />
            <Metric
              icon={<Activity size={18} />}
              label="평가금액"
              value={`${formatMoney(brief?.total_market_value)} KRW`}
            />
            <Metric
              icon={<Check size={18} />}
              label="최근 수집"
              value={formatDate(brief?.latest_collected_at ?? null)}
            />
          </section>

          <div className="contentGrid">
            <section className="mainPanel">
              <div className="sectionHeader">
                <h2>포트폴리오 브리프</h2>
                <span className="countBadge">{brief?.latest_items.length ?? 0}</span>
              </div>
              <div className="positionsTable">
                <div className="tableHead">
                  <span>종목</span>
                  <span>평가금액</span>
                  <span>이슈</span>
                  <span>최근 수집</span>
                </div>
                {brief?.positions.map((position) => (
                  <button
                    key={position.symbol.id}
                    className="tableRow"
                    onClick={() => setSelectedId(position.symbol.id)}
                  >
                    <span>
                      <strong>{position.symbol.name}</strong>
                      <small>
                        {position.symbol.market}:{position.symbol.code}
                      </small>
                    </span>
                    <span>{formatMoney(position.symbol.holding?.market_value)}</span>
                    <span>{position.news_count + position.disclosure_count}</span>
                    <span>{formatDate(position.latest_collected_at)}</span>
                  </button>
                ))}
                {!brief?.positions.length && <div className="emptyState">브리프가 비어 있습니다.</div>}
              </div>

              <div className="issueList">
                {brief?.latest_items.map((item) => (
                  <BriefIssue key={`${item.kind}-${item.symbol_id}-${item.title}`} item={item} />
                ))}
              </div>
            </section>

            <section className="detailPanel">
              {detail && selectedSymbol ? (
                <DetailView
                  detail={detail}
                  form={editForm}
                  onFormChange={setEditForm}
                  onSave={handleSave}
                  onDelete={handleDelete}
                  onMockActivity={handleMockActivity}
                  disabled={isBusy}
                />
              ) : (
                <div className="emptyDetail">
                  <Search size={28} />
                  <span>종목을 선택하세요.</span>
                </div>
              )}
            </section>
          </div>
        </main>
      </div>
    </div>
  );
}

function Metric({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="metric">
      <span className="metricIcon">{icon}</span>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function SymbolForm({
  form,
  onChange,
  onSubmit,
  submitLabel,
  submitIcon,
  disabled,
  allowPartialIdentity = false,
  onLookup,
}: {
  form: FormState;
  onChange: (value: FormState) => void;
  onSubmit: (event: FormEvent) => void;
  submitLabel: string;
  submitIcon: React.ReactNode;
  disabled: boolean;
  allowPartialIdentity?: boolean;
  onLookup?: () => void;
}) {
  function patch(key: keyof FormState, value: string) {
    onChange({ ...form, [key]: value });
  }

  return (
    <form className="symbolForm" onSubmit={onSubmit}>
      <div className="formGrid two">
        <label>
          시장
          <select value={form.market} onChange={(event) => patch("market", event.target.value)}>
            <option value="KOSPI">KOSPI</option>
            <option value="KOSDAQ">KOSDAQ</option>
          </select>
        </label>
        <label>
          코드
          <input
            value={form.code}
            onChange={(event) => patch("code", event.target.value)}
            placeholder="005930"
            required={!allowPartialIdentity}
          />
        </label>
      </div>
      <label>
        종목명
        <input
          value={form.name}
          onChange={(event) => patch("name", event.target.value)}
          placeholder="삼성전자"
          required={!allowPartialIdentity}
        />
      </label>
      <label>
        메모
        <textarea value={form.memo} onChange={(event) => patch("memo", event.target.value)} rows={2} />
      </label>
      <div className="formGrid two">
        <label>
          수량
          <input inputMode="decimal" value={form.quantity} onChange={(event) => patch("quantity", event.target.value)} />
        </label>
        <label>
          평단
          <input inputMode="decimal" value={form.average_cost} onChange={(event) => patch("average_cost", event.target.value)} />
        </label>
        <label>
          평가금액
          <input inputMode="decimal" value={form.market_value} onChange={(event) => patch("market_value", event.target.value)} />
        </label>
        <label>
          비중 %
          <input inputMode="decimal" value={form.portfolio_weight} onChange={(event) => patch("portfolio_weight", event.target.value)} />
        </label>
      </div>
      <div className="formActions">
        {onLookup && (
          <button className="secondaryButton" type="button" onClick={onLookup} disabled={disabled}>
            <Search size={16} />
            검색
          </button>
        )}
        <button className="primaryButton" type="submit" disabled={disabled}>
          {submitIcon}
          {submitLabel}
        </button>
      </div>
    </form>
  );
}

function DetailView({
  detail,
  form,
  onFormChange,
  onSave,
  onDelete,
  onMockActivity,
  disabled,
}: {
  detail: SymbolDetail;
  form: FormState;
  onFormChange: (value: FormState) => void;
  onSave: (event: FormEvent) => void;
  onDelete: () => void;
  onMockActivity: () => void;
  disabled: boolean;
}) {
  return (
    <div className="detailStack">
      <div className="detailHeader">
        <div>
          <span className="marketPill">{detail.market}</span>
          <h1>{detail.name}</h1>
          <p>{detail.code}</p>
        </div>
        <div className="detailActions">
          <button className="compactButton" onClick={onMockActivity} disabled={disabled}>
            <DatabaseZap size={15} />
            샘플 이슈
          </button>
          <button className="dangerButton" onClick={onDelete} disabled={disabled} title="삭제">
            <Trash2 size={16} />
          </button>
        </div>
      </div>

      <SymbolForm
        form={form}
        onChange={onFormChange}
        onSubmit={onSave}
        submitLabel="저장"
        submitIcon={<Save size={16} />}
        disabled={disabled}
      />

      <div className="splitLists">
        <section>
          <div className="sectionHeader">
            <h2>뉴스</h2>
            <Newspaper size={17} />
          </div>
          <div className="issueList compact">
            {detail.news_items.map((entry) => (
              <NewsCard key={entry.item.id} entry={entry} />
            ))}
            {!detail.news_items.length && <div className="emptyState">뉴스가 없습니다.</div>}
          </div>
        </section>

        <section>
          <div className="sectionHeader">
            <h2>공시</h2>
            <FileText size={17} />
          </div>
          <div className="issueList compact">
            {detail.disclosures.map((entry) => (
              <DisclosureCard key={entry.item.id} entry={entry} />
            ))}
            {!detail.disclosures.length && <div className="emptyState">공시가 없습니다.</div>}
          </div>
        </section>
      </div>
    </div>
  );
}

function BriefIssue({ item }: { item: BriefItem }) {
  return (
    <article className="issueCard">
      <div className="issueMeta">
        <span className={`kindPill ${item.kind}`}>{item.kind === "news" ? "뉴스" : "공시"}</span>
        <span>{item.symbol_name}</span>
        <span>{formatDate(item.occurred_at)}</span>
      </div>
      <h3>{item.title}</h3>
      <div className="issueFooter">
        <AnalysisBadges sentiment={item.sentiment} importance={item.importance} />
        <a href={item.original_url} target="_blank" rel="noreferrer">
          <ExternalLink size={14} />
          원문
        </a>
      </div>
    </article>
  );
}

function NewsCard({ entry }: { entry: AnalyzedNewsItem }) {
  return (
    <article className="issueCard">
      <div className="issueMeta">
        <span className="kindPill news">뉴스</span>
        <span>{entry.item.source ?? "News"}</span>
        <span>{formatDate(entry.item.published_at ?? entry.item.collected_at)}</span>
      </div>
      <h3>{entry.item.title}</h3>
      {entry.analysis && <p>{entry.analysis.summary}</p>}
      <AnalysisFooter analysis={entry.analysis} url={entry.item.original_url} />
    </article>
  );
}

function DisclosureCard({ entry }: { entry: AnalyzedDisclosure }) {
  return (
    <article className="issueCard">
      <div className="issueMeta">
        <span className="kindPill disclosure">공시</span>
        <span>{entry.item.rcept_no}</span>
        <span>{formatDate(entry.item.submitted_at ?? entry.item.collected_at)}</span>
      </div>
      <h3>{entry.item.report_name}</h3>
      {entry.analysis && <p>{entry.analysis.portfolio_impact}</p>}
      <AnalysisFooter analysis={entry.analysis} url={entry.item.original_url} />
    </article>
  );
}

function AnalysisFooter({
  analysis,
  url,
}: {
  analysis: { sentiment: Sentiment; importance: number } | null;
  url: string;
}) {
  return (
    <div className="issueFooter">
      <AnalysisBadges sentiment={analysis?.sentiment} importance={analysis?.importance} />
      <a href={url} target="_blank" rel="noreferrer">
        <ExternalLink size={14} />
        원문
      </a>
    </div>
  );
}

function AnalysisBadges({
  sentiment,
  importance,
}: {
  sentiment: Sentiment | null | undefined;
  importance: number | null | undefined;
}) {
  return (
    <span className="badgeGroup">
      <span className={`sentiment ${sentiment ?? "none"}`}>{sentimentLabel(sentiment)}</span>
      <span className="importance">중요도 {importance ?? "-"}</span>
    </span>
  );
}

export default App;
