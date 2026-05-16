import {
  ArrowRight,
  ArrowUpRight,
  Bookmark,
  Check,
  ChevronDown,
  ChevronLeft,
  FileText,
  GripVertical,
  Info,
  Lightbulb,
  Moon,
  Paperclip,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Sun,
  X,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import { api, SymbolPayload } from "./api";
import type {
  AnalysisResult,
  PortfolioBrief,
  Sentiment,
  SymbolDetail,
  SymbolLookupResult,
  SymbolRecord,
} from "./types";

type ViewName = "dashboard" | "feed";
type IssueType = "news" | "disc" | "rep";
type SentKey = "pos" | "neg" | "neu";
type MarketFilter = "all" | "KOSPI" | "KOSDAQ";

type ResearchStock = {
  id: number;
  code: string;
  name: string;
  market: string;
  quantity: number | null;
  averageCost: number | null;
  marketValue: number;
  price: number;
  changePct: number;
  profitLoss: number;
  profitLossPct: number;
  issueCount: number;
  newsCount: number;
  disclosureCount: number;
  reportCount: number;
  latestCollectedAt: string | null;
  dominantSent: SentKey;
  spark: number[];
};

type ResearchIssue = {
  id: string;
  itemId: number;
  stockId: number;
  stockCode: string;
  stockName: string;
  market: string;
  type: IssueType;
  source: string;
  title: string;
  url: string;
  occurredAt: string | null;
  collectedAt: string;
  sentiment: SentKey;
  importance: number;
  summary: string;
  impact: string;
  rationale: string;
  keywords: string[];
  modelVersion: string;
};

type FeedFilter = {
  stockCode?: string | null;
  type?: IssueType | null;
  sentiment?: SentKey | null;
  minImportance?: number;
};

type RegisterState = {
  market: MarketFilter;
  query: string;
  selected: SymbolLookupResult | null;
  quantity: string;
  averageCost: string;
  memo: string;
};

const blankRegisterState: RegisterState = {
  market: "all",
  query: "",
  selected: null,
  quantity: "",
  averageCost: "",
  memo: "",
};

const orbitConfigs = [
  { r: 205, start: 138, period: 118 },
  { r: 140, start: 250, period: 96 },
  { r: 220, start: 204, period: 132 },
  { r: 165, start: 322, period: 86 },
  { r: 235, start: 18, period: 148 },
  { r: 185, start: 54, period: 156 },
  { r: 225, start: 300, period: 141 },
  { r: 150, start: 76, period: 127 },
];

function numberOrNull(value: string): number | null {
  const normalized = value.replace(/,/g, "").trim();
  if (!normalized) return null;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatDate(value: string | null): string {
  if (!value) return "방금";
  return new Intl.DateTimeFormat("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatTime(value: string | null): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatMoney(value: number | null | undefined): string {
  if (!value) return "-";
  return `₩${new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 }).format(value)}`;
}

function formatSignedMoney(value: number): string {
  const abs = Math.abs(value);
  return `${value >= 0 ? "+" : "-"}₩${new Intl.NumberFormat("ko-KR", {
    maximumFractionDigits: 0,
  }).format(abs)}`;
}

function formatPct(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
}

function toSentKey(sentiment: Sentiment | null | undefined): SentKey {
  if (sentiment === "positive") return "pos";
  if (sentiment === "negative") return "neg";
  return "neu";
}

function sentimentLabel(sentiment: SentKey): string {
  if (sentiment === "pos") return "긍정";
  if (sentiment === "neg") return "부정";
  return "중립";
}

function typeLabel(type: IssueType): string {
  if (type === "news") return "NEWS";
  if (type === "disc") return "공시";
  return "리포트";
}

function pseudoSparkline(code: string, baseValue: number, profitLoss: number): number[] {
  const base = baseValue > 0 ? baseValue : 100;
  const seed = code.split("").reduce((sum, char) => sum + char.charCodeAt(0), 0);
  const drift = profitLoss >= 0 ? 0.004 : -0.004;
  return Array.from({ length: 12 }, (_, index) => {
    const wave = Math.sin((seed + index * 7) * 0.37) * 0.018;
    const small = Math.cos((seed + index * 11) * 0.19) * 0.009;
    return Math.max(base * (1 + wave + small + drift * index), 1);
  });
}

function analysisKeywords(analysis: AnalysisResult | null): string[] {
  const source = `${analysis?.summary ?? ""} ${analysis?.portfolio_impact ?? ""} ${analysis?.rationale ?? ""}`;
  const candidates = [
    "수주",
    "계약",
    "실적",
    "매출",
    "원가",
    "마진",
    "주주",
    "리스크",
    "반도체",
    "플랫폼",
    "공시",
    "변동성",
  ];
  const found = candidates.filter((keyword) => source.includes(keyword));
  return found.length ? found.slice(0, 5) : ["요약", "중요도", "포트폴리오"];
}

function buildIssues(details: SymbolDetail[]): ResearchIssue[] {
  const issues = details.flatMap((detail) => {
    const news = detail.news_items.map(({ item, analysis }) => ({
      id: `news-${item.id}`,
      itemId: item.id,
      stockId: detail.id,
      stockCode: detail.code,
      stockName: detail.name,
      market: detail.market,
      type: "news" as const,
      source: item.source ?? "News",
      title: item.title,
      url: item.original_url,
      occurredAt: item.published_at ?? item.collected_at,
      collectedAt: item.collected_at,
      sentiment: toSentKey(analysis?.sentiment),
      importance: analysis?.importance ?? 0,
      summary: analysis?.summary ?? item.summary ?? "요약 대기 중입니다.",
      impact: analysis?.portfolio_impact ?? "포트폴리오 영향 분석 대기 중입니다.",
      rationale: analysis?.rationale ?? "분석 근거가 아직 생성되지 않았습니다.",
      keywords: analysisKeywords(analysis),
      modelVersion: analysis?.model_version ?? "v2.1",
    }));
    const disclosures = detail.disclosures.map(({ item, analysis }) => ({
      id: `disc-${item.id}`,
      itemId: item.id,
      stockId: detail.id,
      stockCode: detail.code,
      stockName: detail.name,
      market: detail.market,
      type: "disc" as const,
      source: "DART",
      title: item.report_name,
      url: item.original_url,
      occurredAt: item.submitted_at ?? item.collected_at,
      collectedAt: item.collected_at,
      sentiment: toSentKey(analysis?.sentiment),
      importance: analysis?.importance ?? 0,
      summary: analysis?.summary ?? `${item.report_name} 공시가 수집되었습니다.`,
      impact: analysis?.portfolio_impact ?? "공시 영향 분석 대기 중입니다.",
      rationale: analysis?.rationale ?? `접수번호 ${item.rcept_no}`,
      keywords: analysisKeywords(analysis),
      modelVersion: analysis?.model_version ?? "v2.1",
    }));
    return [...news, ...disclosures];
  });

  return issues.sort(
    (a, b) =>
      new Date(b.occurredAt ?? b.collectedAt).getTime() -
      new Date(a.occurredAt ?? a.collectedAt).getTime(),
  );
}

function buildStocks(
  symbols: SymbolRecord[],
  brief: PortfolioBrief | null,
  issues: ResearchIssue[],
): ResearchStock[] {
  const briefById = new Map(brief?.positions.map((position) => [position.symbol.id, position]));
  return symbols.map((symbol) => {
    const position = briefById.get(symbol.id);
    const quantity = symbol.holding?.quantity ?? null;
    const averageCost = symbol.holding?.average_cost ?? null;
    const marketValue = symbol.holding?.market_value ?? 0;
    const price = quantity && quantity > 0 ? marketValue / quantity : averageCost ?? marketValue;
    const cost = quantity && averageCost ? quantity * averageCost : marketValue;
    const profitLoss = marketValue - cost;
    const profitLossPct = cost > 0 ? (profitLoss / cost) * 100 : 0;
    const stockIssues = issues.filter((issue) => issue.stockId === symbol.id);
    const sentimentCounts = stockIssues.reduce(
      (acc, issue) => ({ ...acc, [issue.sentiment]: acc[issue.sentiment] + 1 }),
      { pos: 0, neg: 0, neu: 0 } satisfies Record<SentKey, number>,
    );
    const dominantSent =
      sentimentCounts.pos > sentimentCounts.neg && sentimentCounts.pos >= sentimentCounts.neu
        ? "pos"
        : sentimentCounts.neg > sentimentCounts.pos && sentimentCounts.neg >= sentimentCounts.neu
          ? "neg"
          : "neu";
    const newsCount = position?.news_count ?? stockIssues.filter((issue) => issue.type === "news").length;
    const disclosureCount =
      position?.disclosure_count ?? stockIssues.filter((issue) => issue.type === "disc").length;
    return {
      id: symbol.id,
      code: symbol.code,
      name: symbol.name,
      market: symbol.market,
      quantity,
      averageCost,
      marketValue,
      price,
      changePct: profitLossPct,
      profitLoss,
      profitLossPct,
      issueCount: newsCount + disclosureCount,
      newsCount,
      disclosureCount,
      reportCount: 0,
      latestCollectedAt: position?.latest_collected_at ?? null,
      dominantSent,
      spark: pseudoSparkline(symbol.code, price, profitLoss),
    };
  });
}

function payloadFromRegistration(state: RegisterState): SymbolPayload {
  const quantity = numberOrNull(state.quantity);
  const averageCost = numberOrNull(state.averageCost);
  const marketValue = quantity && averageCost ? quantity * averageCost : null;
  const hasHolding = [quantity, averageCost, marketValue].some((value) => value !== null);
  return {
    market: state.selected?.market ?? "KOSPI",
    code: state.selected?.code ?? state.query,
    name: state.selected?.name ?? "",
    memo: state.memo.trim() || null,
    holding: hasHolding
      ? {
          quantity,
          average_cost: averageCost,
          market_value: marketValue,
          portfolio_weight: null,
        }
      : null,
  };
}

function App() {
  const [view, setView] = useState<ViewName>("dashboard");
  const [symbols, setSymbols] = useState<SymbolRecord[]>([]);
  const [brief, setBrief] = useState<PortfolioBrief | null>(null);
  const [details, setDetails] = useState<SymbolDetail[]>([]);
  const [selectedIssueId, setSelectedIssueId] = useState<string | null>(null);
  const [filter, setFilter] = useState<FeedFilter>({});
  const [modalOpen, setModalOpen] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [isLoading, setIsLoading] = useState(true);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [secondsLeft, setSecondsLeft] = useState(272);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    document.documentElement.setAttribute("data-accent", "ink");
  }, [theme]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setSecondsLeft((value) => (value <= 0 ? 300 : value - 1));
    }, 1000);
    return () => window.clearInterval(timer);
  }, []);

  const countdown = useMemo(() => {
    const minutes = Math.floor(secondsLeft / 60);
    const seconds = secondsLeft % 60;
    return `${minutes}:${String(seconds).padStart(2, "0")}`;
  }, [secondsLeft]);

  const issues = useMemo(() => buildIssues(details), [details]);
  const stocks = useMemo(() => buildStocks(symbols, brief, issues), [symbols, brief, issues]);
  const registeredCodes = useMemo(() => symbols.map((symbol) => symbol.code), [symbols]);

  const refresh = useCallback(async () => {
    const [nextBrief, nextSymbols] = await Promise.all([api.getBrief(), api.listSymbols()]);
    const nextDetails = await Promise.all(nextSymbols.map((symbol) => api.getSymbol(symbol.id)));
    setBrief(nextBrief);
    setSymbols(nextSymbols);
    setDetails(nextDetails);
  }, []);

  useEffect(() => {
    refresh()
      .catch((err: Error) => setError(err.message))
      .finally(() => setIsLoading(false));
  }, [refresh]);

  useEffect(() => {
    if (!selectedIssueId && issues.length) {
      setSelectedIssueId(issues[0].id);
    }
    if (selectedIssueId && issues.length && !issues.some((issue) => issue.id === selectedIssueId)) {
      setSelectedIssueId(issues[0].id);
    }
  }, [issues, selectedIssueId]);

  async function runAction(action: () => Promise<void>) {
    setIsBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : "작업에 실패했습니다.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleRefreshCollection() {
    await runAction(async () => {
      await Promise.all(symbols.map((symbol) => api.createMockActivity(symbol.id)));
      await refresh();
      setSecondsLeft(300);
    });
  }

  async function handleRegister(state: RegisterState) {
    await runAction(async () => {
      const created = await api.createSymbol(payloadFromRegistration(state));
      await api.createMockActivity(created.id);
      await refresh();
      setView("dashboard");
    });
  }

  function goToFeed(stockCode?: string) {
    setFilter(stockCode ? { stockCode } : {});
    setSelectedIssueId(null);
    setView("feed");
  }

  const isEmpty = !isLoading && symbols.length === 0;

  return (
    <div className="app">
      <AppBar
        view={view}
        setView={setView}
        countdown={countdown}
        refreshing={isBusy}
        onRefresh={handleRefreshCollection}
        onAddStock={() => setModalOpen(true)}
        theme={theme}
        setTheme={setTheme}
      />

      <main className="app-main">
        <StatusLine isLoading={isLoading} error={error} />
        {isEmpty ? (
          <EmptyState onAddStock={() => setModalOpen(true)} />
        ) : view === "dashboard" ? (
          <Dashboard
            stocks={stocks}
            issues={issues}
            brief={brief}
            countdown={countdown}
            refreshing={isBusy}
            onRefresh={handleRefreshCollection}
            onPlanetClick={(stock) => goToFeed(stock.code)}
          />
        ) : (
          <Feed
            stocks={stocks}
            issues={issues}
            filter={filter}
            setFilter={setFilter}
            selectedIssueId={selectedIssueId}
            setSelectedIssueId={setSelectedIssueId}
          />
        )}
      </main>

      <RegisterModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onRegister={handleRegister}
        registeredCodes={registeredCodes}
        disabled={isBusy}
      />
    </div>
  );
}

function AppBar({
  view,
  setView,
  countdown,
  refreshing,
  onRefresh,
  onAddStock,
  theme,
  setTheme,
}: {
  view: ViewName;
  setView: (view: ViewName) => void;
  countdown: string;
  refreshing: boolean;
  onRefresh: () => void;
  onAddStock: () => void;
  theme: "light" | "dark";
  setTheme: (theme: "light" | "dark") => void;
}) {
  return (
    <header className="app-bar">
      <div className="logo">
        <div className="logo-mark">k</div>
        <span>KOSPI Reporter</span>
      </div>
      <nav className="nav" aria-label="주요 화면">
        <button
          className="nav-item"
          aria-current={view === "dashboard" ? "page" : undefined}
          onClick={() => setView("dashboard")}
        >
          대시보드
        </button>
        <button
          className="nav-item"
          aria-current={view === "feed" ? "page" : undefined}
          onClick={() => setView("feed")}
        >
          통합 피드
        </button>
      </nav>
      <div className="right">
        <button className="status-pill" onClick={onRefresh} disabled={refreshing} title="지금 새로고침">
          <span className="pulse" />
          <span>
            다음 수집 <b className="mono">{countdown}</b>
          </span>
          <RefreshCw size={13} className={refreshing ? "spin" : ""} />
        </button>
        <Button variant="primary" size="sm" icon={<Plus size={14} />} onClick={onAddStock}>
          종목 추가
        </Button>
        <IconButton
          title={theme === "dark" ? "라이트 모드" : "다크 모드"}
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
        >
          {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
        </IconButton>
      </div>
    </header>
  );
}

function StatusLine({
  isLoading,
  error,
}: {
  isLoading: boolean;
  error: string | null;
}) {
  if (!isLoading && !error) return null;
  return (
    <div className="status-line" role="status">
      {isLoading && <span>불러오는 중</span>}
      {error && <span className="error">{error}</span>}
    </div>
  );
}

function Dashboard({
  stocks,
  issues,
  brief,
  countdown,
  refreshing,
  onRefresh,
  onPlanetClick,
}: {
  stocks: ResearchStock[];
  issues: ResearchIssue[];
  brief: PortfolioBrief | null;
  countdown: string;
  refreshing: boolean;
  onRefresh: () => void;
  onPlanetClick: (stock: ResearchStock) => void;
}) {
  return (
    <div className="dashboard">
      <CollectionPane
        stocks={stocks}
        issues={issues}
        brief={brief}
        countdown={countdown}
        refreshing={refreshing}
        onRefresh={onRefresh}
        onPlanetClick={onPlanetClick}
      />
      <HoldingsPane stocks={stocks} brief={brief} onOpen={onPlanetClick} />
    </div>
  );
}

function CollectionPane({
  stocks,
  issues,
  brief,
  countdown,
  refreshing,
  onRefresh,
  onPlanetClick,
}: {
  stocks: ResearchStock[];
  issues: ResearchIssue[];
  brief: PortfolioBrief | null;
  countdown: string;
  refreshing: boolean;
  onRefresh: () => void;
  onPlanetClick: (stock: ResearchStock) => void;
}) {
  const recent = issues[0] ?? null;
  const recentStock = recent ? stocks.find((stock) => stock.code === recent.stockCode) : null;
  const totalNew = stocks.reduce((sum, stock) => sum + stock.issueCount, 0);
  return (
    <section className="dash-pane dash-pane--left">
      <div className="dash-pane-head">
        <h2>수집 · 자료</h2>
        <span className="meta">마지막 {formatDate(brief?.latest_collected_at ?? null)} · 자동 5분</span>
      </div>
      <Orbital
        stocks={stocks}
        countdown={countdown}
        onRefresh={onRefresh}
        refreshing={refreshing}
        onPlanetClick={onPlanetClick}
      />
      <div className="orbital-foot">
        <span>
          <b>{totalNew}건</b> 새 정보
        </span>
        <span>오늘 수집 {Math.max(brief?.latest_items.length ?? 0, issues.length)}건 · 실패 0</span>
      </div>
      {recent && recentStock && (
        <button className="recent-arrival" onClick={() => onPlanetClick(recentStock)}>
          <span className="meta">최근 도착</span>
          <span className="when soft">{formatTime(recent.occurredAt)}</span>
          <SentGlyph sentiment={recent.sentiment} />
          <span className="recent-stock">{recentStock.name}</span>
          <span className="recent-title">· {recent.title}</span>
        </button>
      )}
    </section>
  );
}

function HoldingsPane({
  stocks,
  brief,
  onOpen,
}: {
  stocks: ResearchStock[];
  brief: PortfolioBrief | null;
  onOpen: (stock: ResearchStock) => void;
}) {
  const totalMarketValue = brief?.total_market_value ?? stocks.reduce((sum, stock) => sum + stock.marketValue, 0);
  const totalCost = stocks.reduce((sum, stock) => {
    if (!stock.quantity || !stock.averageCost) return sum + stock.marketValue;
    return sum + stock.quantity * stock.averageCost;
  }, 0);
  const totalProfit = totalMarketValue - totalCost;
  const totalProfitPct = totalCost > 0 ? (totalProfit / totalCost) * 100 : 0;
  return (
    <section className="dash-pane">
      <div className="holdings-head">
        <h2>내 보유</h2>
        <span className="sort">
          비중순 <ChevronDown size={12} />
        </span>
      </div>
      <div className="holdings-summary">
        <div>
          <span className="lbl">평가금액</span>
          <span className="num">{formatMoney(totalMarketValue)}</span>
        </div>
        <div>
          <span className="lbl">평가손익</span>
          <span className="num">
            {formatSignedMoney(totalProfit)}
            <span className={`delta ${totalProfit >= 0 ? "delta--pos" : "delta--neg"}`}>
              {formatPct(totalProfitPct)}
            </span>
          </span>
        </div>
        <span className="spacer" />
      </div>
      <div className="holdings-grid">
        {stocks.map((stock) => (
          <StockCard key={stock.id} stock={stock} onOpen={() => onOpen(stock)} />
        ))}
      </div>
    </section>
  );
}

function StockCard({ stock, onOpen }: { stock: ResearchStock; onOpen: () => void }) {
  const up = stock.changePct >= 0;
  return (
    <button className="stock-card" onClick={onOpen}>
      <div className="row">
        <span className="drag-handle">
          <GripVertical size={14} />
        </span>
        <span className="name">{stock.name}</span>
        <span className="spacer" />
        <MktChip market={stock.market} />
      </div>
      <div className="row stock-price-row">
        <span className="price">{formatMoney(stock.price)}</span>
        <span className={`chg ${up ? "chg--pos" : "chg--neg"}`}>
          {up ? "▲" : "▼"} {Math.abs(stock.changePct).toFixed(1)}%
        </span>
      </div>
      <Sparkline data={stock.spark} positive={up} />
      <div className="foot">
        <span className="pos-info">
          {stock.quantity ?? "-"}주 · 평단 {stock.averageCost ? stock.averageCost.toLocaleString() : "-"}
        </span>
        <span className={`pl ${stock.profitLoss >= 0 ? "pl--pos" : "pl--neg"}`}>
          {formatSignedMoney(stock.profitLoss)} ({formatPct(stock.profitLossPct)})
        </span>
      </div>
    </button>
  );
}

function Orbital({
  stocks,
  countdown,
  refreshing,
  onRefresh,
  onPlanetClick,
}: {
  stocks: ResearchStock[];
  countdown: string;
  refreshing: boolean;
  onRefresh: () => void;
  onPlanetClick: (stock: ResearchStock) => void;
}) {
  const [hover, setHover] = useState<string | null>(null);
  return (
    <div className="orbital">
      {[140, 200, 250].map((radius) => (
        <span key={radius} className="orbital-ring" style={{ width: radius * 2, height: radius * 2 }} />
      ))}
      <div className="orbital-hub">
        <span className="label">다음 자동 수집</span>
        <span className="countdown">{refreshing ? "수집 중" : countdown}</span>
        <button className="refresh-btn" onClick={onRefresh} data-loading={refreshing ? "true" : "false"}>
          <RefreshCw size={12} />
          지금
        </button>
      </div>
      {stocks.map((stock, index) => {
        const cfg = orbitConfigs[index % orbitConfigs.length];
        const delay = -((cfg.start / 360) * cfg.period);
        return (
          <div
            key={stock.id}
            className="orbit-arm"
            style={{
              animationDuration: `${cfg.period}s`,
              animationDelay: `${delay}s`,
              zIndex: hover === stock.code ? 10 : 2,
            }}
          >
            <div className="orbit-radius" style={{ transform: `translate(${cfg.r}px, 0)` }}>
              <div
                className="orbit-counter"
                style={{
                  animationDuration: `${cfg.period}s`,
                  animationDelay: `${delay}s`,
                }}
              >
                <div className="orbit-planet-anchor">
                  <Planet
                    stock={stock}
                    hovered={hover === stock.code}
                    onHover={setHover}
                    onClick={onPlanetClick}
                  />
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Planet({
  stock,
  hovered,
  onHover,
  onClick,
}: {
  stock: ResearchStock;
  hovered: boolean;
  onHover: (code: string | null) => void;
  onClick: (stock: ResearchStock) => void;
}) {
  const size = stock.issueCount > 0 ? Math.min(82, 28 + stock.issueCount * 10.5) : 28;
  const hasNews = stock.issueCount > 0;
  const fontSize = Math.max(11, Math.min(22, size * 0.42));
  return (
    <button
      className="planet"
      data-hover={hovered ? "true" : "false"}
      data-has-news={hasNews ? "true" : "false"}
      onMouseEnter={() => onHover(stock.code)}
      onMouseLeave={() => onHover(null)}
      onFocus={() => onHover(stock.code)}
      onBlur={() => onHover(null)}
      onClick={() => onClick(stock)}
      aria-label={`${stock.name}: 뉴스 ${stock.newsCount}, 공시 ${stock.disclosureCount}, 리포트 ${stock.reportCount}`}
    >
      <span
        className="planet-disc"
        data-has-news={hasNews ? "true" : "false"}
        style={{ width: size, height: size, fontSize }}
      >
        {hasNews ? stock.issueCount : ""}
        {hasNews && <span className="planet-blip" />}
      </span>
      <span className="planet-label">{stock.name}</span>
      {hovered && (
        <span className="planet-tooltip" role="tooltip">
          <span>
            <span className="ttkey">뉴스</span> <b>{stock.newsCount}</b>
          </span>
          <span>
            <span className="ttkey">공시</span> <b>{stock.disclosureCount}</b>
          </span>
          <span>
            <span className="ttkey">리포트</span> <b>{stock.reportCount}</b>
          </span>
        </span>
      )}
    </button>
  );
}

function Feed({
  stocks,
  issues,
  filter,
  setFilter,
  selectedIssueId,
  setSelectedIssueId,
}: {
  stocks: ResearchStock[];
  issues: ResearchIssue[];
  filter: FeedFilter;
  setFilter: (filter: FeedFilter) => void;
  selectedIssueId: string | null;
  setSelectedIssueId: (id: string | null) => void;
}) {
  const visible = useMemo(
    () =>
      issues.filter((issue) => {
        if (filter.stockCode && issue.stockCode !== filter.stockCode) return false;
        if (filter.type && issue.type !== filter.type) return false;
        if (filter.sentiment && issue.sentiment !== filter.sentiment) return false;
        if (filter.minImportance && issue.importance < filter.minImportance) return false;
        return true;
      }),
    [issues, filter],
  );
  const stockMap = useMemo(() => new Map(stocks.map((stock) => [stock.code, stock])), [stocks]);
  const selected = visible.find((issue) => issue.id === selectedIssueId) ?? visible[0] ?? null;

  useEffect(() => {
    if (selected && selected.id !== selectedIssueId) {
      setSelectedIssueId(selected.id);
    }
  }, [selected, selectedIssueId, setSelectedIssueId]);

  return (
    <div className="col feed-view">
      <FeedFilters stocks={stocks} filter={filter} setFilter={setFilter} />
      <div className="feed">
        <div className="feed-list">
          {visible.length === 0 && (
            <div className="feed-pane-empty">
              <span>조건에 맞는 항목이 없어요</span>
              <Button size="sm" variant="ghost" onClick={() => setFilter({})}>
                필터 초기화
              </Button>
            </div>
          )}
          {visible.map((issue) => (
            <FeedListItem
              key={issue.id}
              issue={issue}
              selected={selected?.id === issue.id}
              onClick={() => setSelectedIssueId(issue.id)}
            />
          ))}
        </div>
        <FeedReadingPane issue={selected} stock={selected ? stockMap.get(selected.stockCode) ?? null : null} />
      </div>
    </div>
  );
}

function FeedFilters({
  stocks,
  filter,
  setFilter,
}: {
  stocks: ResearchStock[];
  filter: FeedFilter;
  setFilter: (filter: FeedFilter) => void;
}) {
  const types: Array<{ value: IssueType | "all"; label: string }> = [
    { value: "all", label: "전체" },
    { value: "news", label: "뉴스" },
    { value: "disc", label: "공시" },
    { value: "rep", label: "리포트" },
  ];
  const sentiments: Array<{ value: SentKey | "all"; label: string }> = [
    { value: "all", label: "감성 전체" },
    { value: "pos", label: "긍정" },
    { value: "neu", label: "중립" },
    { value: "neg", label: "부정" },
  ];
  return (
    <div className="feed-filters">
      <span className="filter-label">종목</span>
      <div className="filter-group">
        <Chip active={!filter.stockCode} onClick={() => setFilter({ ...filter, stockCode: null })}>
          전체
        </Chip>
        {stocks.slice(0, 6).map((stock) => (
          <Chip
            key={stock.id}
            active={filter.stockCode === stock.code}
            onClick={() =>
              setFilter({ ...filter, stockCode: filter.stockCode === stock.code ? null : stock.code })
            }
          >
            {stock.name}
          </Chip>
        ))}
        {stocks.length > 6 && (
          <button className="chip chip--ghost" title="더 보기">
            <ChevronDown size={12} />
          </button>
        )}
      </div>
      <span className="divider" />
      <div className="filter-group">
        {types.map((type) => (
          <Chip
            key={type.value}
            active={filter.type === type.value || (type.value === "all" && !filter.type)}
            onClick={() => setFilter({ ...filter, type: type.value === "all" ? null : type.value })}
          >
            {type.label}
          </Chip>
        ))}
      </div>
      <span className="divider" />
      <div className="filter-group">
        {sentiments.map((sentiment) => (
          <Chip
            key={sentiment.value}
            active={filter.sentiment === sentiment.value || (sentiment.value === "all" && !filter.sentiment)}
            onClick={() =>
              setFilter({ ...filter, sentiment: sentiment.value === "all" ? null : sentiment.value })
            }
          >
            {sentiment.label}
          </Chip>
        ))}
      </div>
      <span className="divider" />
      <Chip
        ghost
        active={(filter.minImportance ?? 0) >= 4}
        onClick={() =>
          setFilter({ ...filter, minImportance: (filter.minImportance ?? 0) >= 4 ? 0 : 4 })
        }
      >
        중요도 4 이상
      </Chip>
    </div>
  );
}

function FeedListItem({
  issue,
  selected,
  onClick,
}: {
  issue: ResearchIssue;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button className="feed-item" aria-current={selected ? "true" : "false"} onClick={onClick}>
      <span className={`s-rail s-rail--${issue.sentiment}`} />
      <span className="body">
        <span className="meta">
          <MktChip market={issue.market} />
          <span className="feed-stock-name">{issue.stockName}</span>
          <span>·</span>
          <span className="when">{formatTime(issue.occurredAt)}</span>
          <span>·</span>
          <span>{issue.source}</span>
        </span>
        <span className="title">{issue.title}</span>
        <span className="badges">
          <TypeBadge type={issue.type} />
          <ImportanceDots value={issue.importance} />
        </span>
      </span>
    </button>
  );
}

function FeedReadingPane({ issue, stock }: { issue: ResearchIssue | null; stock: ResearchStock | null }) {
  if (!issue || !stock) {
    return (
      <div className="feed-pane">
        <div className="feed-pane-empty">
          <FileText size={36} />
          <div>왼쪽 목록에서 항목을 선택해 주세요</div>
        </div>
      </div>
    );
  }

  return (
    <div className="feed-pane">
      <article className="feed-article">
        <div className="meta-line">
          <TypeBadge type={issue.type} />
          <MktChip market={stock.market} />
          <span>
            <b>{stock.name}</b> · {stock.code}
          </span>
          <span>·</span>
          <span>{issue.source}</span>
          <span>·</span>
          <span className="mono">{formatTime(issue.occurredAt)}</span>
          <span className="spacer" />
          <IconButton title="북마크">
            <Bookmark size={16} />
          </IconButton>
          <a className="icon-btn" href={issue.url} target="_blank" rel="noreferrer" title="원문 새 탭">
            <ArrowUpRight size={16} />
          </a>
        </div>
        <h1>{issue.title}</h1>
        <div className="pills">
          <span>
            <span className="pill-label">감성 </span>
            <SentPill sentiment={issue.sentiment} />
          </span>
          <span>
            <span className="pill-label">중요도 </span>
            <span className="pill-value">
              <ImportanceDots value={issue.importance} /> {issue.importance}/5
            </span>
          </span>
          <span>
            <span className="pill-label">포트폴리오 영향 </span>
            <span className="pill-value">{issue.importance >= 4 ? "높음" : issue.importance >= 3 ? "중간" : "낮음"}</span>
          </span>
          <span className="muted analysis-meta">분석 {issue.modelVersion} · {formatTime(issue.collectedAt)}</span>
        </div>
        <section>
          <h2>
            <Sparkles size={11} /> AI 요약
          </h2>
          <p className="summary">{issue.summary}</p>
        </section>
        <section>
          <h2>포트폴리오 영향 분석</h2>
          <p className="analysis">{issue.impact}</p>
        </section>
        <section>
          <h2>분석 근거</h2>
          <div className="keywords">
            {issue.keywords.map((keyword) => (
              <span key={keyword} className="keyword">
                {keyword}
              </span>
            ))}
          </div>
          <a className="original-card" href={issue.url} target="_blank" rel="noreferrer">
            <span>
              <Paperclip size={14} /> 원문 · {issue.source}
            </span>
            <span className="open-link">
              새 탭으로 열기 <ArrowUpRight size={12} />
            </span>
          </a>
        </section>
        <div className="actions">
          <Button icon={<ChevronLeft size={14} />}>이전</Button>
          <span className="spacer" />
          <Button>메모 추가</Button>
          <Button variant="primary" icon={<ArrowRight size={14} />}>
            다음
          </Button>
        </div>
      </article>
    </div>
  );
}

function RegisterModal({
  open,
  onClose,
  onRegister,
  registeredCodes,
  disabled,
}: {
  open: boolean;
  onClose: () => void;
  onRegister: (state: RegisterState) => Promise<void>;
  registeredCodes: string[];
  disabled: boolean;
}) {
  const [step, setStep] = useState<1 | 2>(1);
  const [form, setForm] = useState<RegisterState>(blankRegisterState);
  const [matches, setMatches] = useState<SymbolLookupResult[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setStep(1);
    setForm(blankRegisterState);
    setMatches([]);
    setSelectedIndex(0);
    setLookupError(null);
    window.setTimeout(() => inputRef.current?.focus(), 60);
  }, [open]);

  useEffect(() => {
    const query = form.query.trim();
    if (!open || !query) {
      setMatches([]);
      setLookupError(null);
      return;
    }

    const timer = window.setTimeout(() => {
      const markets = form.market === "all" ? (["KOSPI", "KOSDAQ"] as const) : [form.market];
      Promise.all(markets.map((market) => api.lookupSymbols(query, market)))
        .then((results) => {
          const seen = new Set<string>();
          const merged = results
            .flat()
            .filter((match) => {
              const key = `${match.market}-${match.code}`;
              if (seen.has(key)) return false;
              seen.add(key);
              return true;
            })
            .slice(0, 8);
          setMatches(merged);
          setSelectedIndex(0);
          setLookupError(null);
        })
        .catch((err: Error) => setLookupError(err.message));
    }, 180);

    return () => window.clearTimeout(timer);
  }, [form.query, form.market, open]);

  if (!open) return null;

  function selectMatch(match: SymbolLookupResult) {
    if (registeredCodes.includes(match.code)) return;
    setForm((value) => ({ ...value, selected: match, market: match.market as MarketFilter }));
    setStep(2);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (!matches.length) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setSelectedIndex((index) => Math.min(index + 1, matches.length - 1));
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setSelectedIndex((index) => Math.max(index - 1, 0));
    }
    if (event.key === "Enter") {
      event.preventDefault();
      selectMatch(matches[selectedIndex]);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!form.selected) return;
    await onRegister(form);
    onClose();
  }

  return (
    <div className="modal-backdrop" onClick={(event) => event.target === event.currentTarget && onClose()}>
      <form className="modal" role="dialog" aria-modal="true" onSubmit={submit}>
        <div className="modal-head">
          <h2>
            종목 추가
            <span className="step-marker">· {step} / 2</span>
          </h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="닫기">
            <X size={18} />
          </button>
        </div>

        <div className="modal-stepper">
          <span className={`dot ${step > 1 ? "dot--done" : "dot--active"}`}>
            {step > 1 ? <Check size={12} /> : 1}
          </span>
          <span className={`label ${step === 1 ? "label--active" : ""}`}>종목 선택</span>
          <span className={`line ${step > 1 ? "line--done" : ""}`} />
          <span className={`dot ${step === 2 ? "dot--active" : ""}`}>2</span>
          <span className={`label ${step === 2 ? "label--active" : ""}`}>보유 정보</span>
        </div>

        {step === 1 && (
          <div className="modal-body">
            <div className="row market-row">
              <span className="field-label">시장</span>
              <Chip active={form.market === "all"} onClick={() => setForm({ ...form, market: "all" })}>
                전체
              </Chip>
              <Chip active={form.market === "KOSPI"} onClick={() => setForm({ ...form, market: "KOSPI" })}>
                KOSPI
              </Chip>
              <Chip active={form.market === "KOSDAQ"} onClick={() => setForm({ ...form, market: "KOSDAQ" })}>
                KOSDAQ
              </Chip>
            </div>

            <div className="search-input-wrap">
              <span className="search-input-icon">
                <Search size={18} />
              </span>
              <input
                ref={inputRef}
                className="search-input"
                placeholder="종목명 또는 코드를 입력하세요 (예: 한화, 005930)"
                value={form.query}
                onChange={(event) => setForm({ ...form, query: event.target.value, selected: null })}
                onKeyDown={handleKeyDown}
              />
              {form.query && (
                <button
                  type="button"
                  className="search-input-clear"
                  onClick={() => {
                    setForm({ ...form, query: "", selected: null });
                    inputRef.current?.focus();
                  }}
                  title="지우기"
                >
                  <X size={14} />
                </button>
              )}
            </div>

            <div className="search-results">
              {form.query.trim() && matches.length > 0 && (
                <div className="results-head">
                  <span>
                    “{form.query.trim()}” 매칭 {matches.length}건 {matches.length === 8 ? "+ " : ""}
                  </span>
                  <span>↑↓ Enter</span>
                </div>
              )}
              {form.query.trim() === "" ? (
                <div className="search-empty">
                  <Search size={28} />
                  <div>
                    코드 또는 종목명 일부를 입력하면
                    <br />
                    자동으로 검색돼요
                  </div>
                </div>
              ) : lookupError ? (
                <div className="search-empty">
                  <span>{lookupError}</span>
                </div>
              ) : matches.length === 0 ? (
                <div className="search-empty">
                  <div>“{form.query.trim()}”와 일치하는 종목을 찾지 못했어요</div>
                  <Button size="sm" onClick={() => setForm({ ...form, query: "", selected: null })}>
                    다시 입력
                  </Button>
                </div>
              ) : (
                <div className="results-list">
                  {matches.map((match, index) => {
                    const registered = registeredCodes.includes(match.code);
                    return (
                      <button
                        type="button"
                        key={`${match.market}-${match.code}`}
                        className="result-item"
                        aria-selected={index === selectedIndex ? "true" : "false"}
                        data-registered={registered ? "true" : "false"}
                        disabled={registered}
                        onMouseEnter={() => setSelectedIndex(index)}
                        onClick={() => selectMatch(match)}
                      >
                        <MktChip market={match.market} />
                        <span className="code">{match.code}</span>
                        <span className="name">
                          <span className="name-text">{highlightMatch(match.name, form.query.trim())}</span>
                          <span className="sector">국내 주식</span>
                        </span>
                        <span className="result-action">
                          {registered ? (
                            <>
                              이미 등록됨 <Check size={12} />
                            </>
                          ) : index === selectedIndex ? (
                            "Enter ⏎"
                          ) : (
                            "선택"
                          )}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="modal-hint">
              <Lightbulb size={14} />
              <span>코드와 종목명으로 검색돼요. ↑↓ 이동, Enter 선택, Esc 닫기.</span>
            </div>
          </div>
        )}

        {step === 2 && form.selected && (
          <div className="modal-body">
            <div className="selected-stock">
              <div className="info">
                <span className="top">
                  <MktChip market={form.selected.market} />
                  <span>{form.selected.code} · 국내 주식</span>
                </span>
                <span className="name">{form.selected.name}</span>
              </div>
              <button type="button" className="change" onClick={() => setStep(1)}>
                <ChevronLeft size={14} /> 변경
              </button>
            </div>

            <div className="section-title-line">
              <h3>보유 정보</h3>
              <span className="muted">· 모두 선택사항</span>
            </div>

            <div className="field-row">
              <div className="field">
                <label className="field-label">보유 수량 (주)</label>
                <input
                  className="field-input"
                  placeholder="예: 80"
                  value={form.quantity}
                  onChange={(event) => setForm({ ...form, quantity: event.target.value })}
                  inputMode="numeric"
                />
              </div>
              <div className="field">
                <label className="field-label">평균 단가 (원)</label>
                <input
                  className="field-input"
                  placeholder="예: 36,500"
                  value={form.averageCost}
                  onChange={(event) => setForm({ ...form, averageCost: event.target.value })}
                  inputMode="numeric"
                />
              </div>
            </div>
            <div className="field">
              <label className="field-label">메모</label>
              <input
                className="field-input"
                placeholder="ex) 수주 모멘텀 관찰"
                value={form.memo}
                onChange={(event) => setForm({ ...form, memo: event.target.value })}
              />
            </div>

            <div className="modal-hint">
              <Info size={14} />
              <span>비워두면 “관심 종목”으로 등록돼요. 보유 정보는 언제든 수정할 수 있어요.</span>
            </div>

            <span className="spacer" />
          </div>
        )}

        <div className="modal-foot">
          {step === 1 ? (
            <>
              <Button type="button" variant="ghost" onClick={onClose}>
                취소
              </Button>
              <span>{matches.length > 0 && "항목을 클릭하거나 Enter로 선택"}</span>
            </>
          ) : (
            <>
              <Button type="button" icon={<ChevronLeft size={14} />} onClick={() => setStep(1)}>
                이전
              </Button>
              <div className="row modal-actions">
                <Button type="submit" disabled={disabled || !form.selected}>
                  비워두고 등록
                </Button>
                <Button type="submit" variant="primary" disabled={disabled || !form.selected} icon={<Plus size={14} />}>
                  등록
                </Button>
              </div>
            </>
          )}
        </div>
      </form>
    </div>
  );
}

function highlightMatch(text: string, query: string): ReactNode {
  if (!query) return text;
  const index = text.toLocaleLowerCase("ko-KR").indexOf(query.toLocaleLowerCase("ko-KR"));
  if (index < 0) return text;
  return (
    <>
      {text.slice(0, index)}
      <b className="match">{text.slice(index, index + query.length)}</b>
      {text.slice(index + query.length)}
    </>
  );
}

function EmptyState({ onAddStock }: { onAddStock: () => void }) {
  return (
    <section className="empty-state">
      <div className="art">
        <span className="art-orbit" />
        <span className="art-dot" style={{ left: 26, top: 62 }} />
        <span className="art-dot" style={{ right: 36, bottom: 54 }} />
        <span className="art-hub">k</span>
      </div>
      <div>
        <h2>아직 등록된 종목이 없습니다</h2>
        <p>관심 종목을 추가하면 뉴스와 공시 수집 결과가 이 대시보드에 표시됩니다.</p>
      </div>
      <Button variant="primary" icon={<Plus size={15} />} onClick={onAddStock}>
        종목 추가
      </Button>
    </section>
  );
}

function Button({
  children,
  icon,
  variant = "default",
  size,
  type = "button",
  disabled,
  onClick,
}: {
  children: ReactNode;
  icon?: ReactNode;
  variant?: "default" | "primary" | "ghost";
  size?: "sm" | "lg";
  type?: "button" | "submit";
  disabled?: boolean;
  onClick?: () => void;
}) {
  const classes = ["btn", variant === "primary" ? "btn--primary" : "", variant === "ghost" ? "btn--ghost" : "", size ? `btn--${size}` : ""]
    .filter(Boolean)
    .join(" ");
  return (
    <button type={type} className={classes} disabled={disabled} onClick={onClick}>
      {icon}
      {children}
    </button>
  );
}

function IconButton({
  children,
  title,
  onClick,
}: {
  children: ReactNode;
  title: string;
  onClick?: () => void;
}) {
  return (
    <button type="button" className="icon-btn" title={title} onClick={onClick}>
      {children}
    </button>
  );
}

function Chip({
  children,
  active,
  ghost,
  onClick,
}: {
  children: ReactNode;
  active?: boolean;
  ghost?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      className={`chip ${active ? "chip--active" : ""} ${ghost ? "chip--ghost" : ""}`}
      aria-pressed={Boolean(active)}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

function MktChip({ market }: { market: string }) {
  return <span className="chip chip--mkt">{market}</span>;
}

function TypeBadge({ type }: { type: IssueType }) {
  return <span className={`type-badge type-badge--${type}`}>{typeLabel(type)}</span>;
}

function ImportanceDots({ value }: { value: number }) {
  return (
    <span className="imp" aria-label={`중요도 ${value}/5`}>
      {[1, 2, 3, 4, 5].map((index) => (
        <span key={index} className={`imp-dot ${index <= value ? "imp-dot--on" : ""}`} />
      ))}
    </span>
  );
}

function SentGlyph({ sentiment }: { sentiment: SentKey }) {
  const glyph = sentiment === "pos" ? "▲" : sentiment === "neg" ? "▼" : "◆";
  return <span className={`sent-glyph sent-glyph--${sentiment}`}>{glyph}</span>;
}

function SentPill({ sentiment }: { sentiment: SentKey }) {
  return (
    <span className={`sent sent--${sentiment}`}>
      <SentGlyph sentiment={sentiment} />
      {sentimentLabel(sentiment)}
    </span>
  );
}

function Sparkline({ data, positive }: { data: number[]; positive: boolean }) {
  const width = 260;
  const height = 36;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const points = data
    .map((value, index) => {
      const x = (index / (data.length - 1)) * width;
      const y = height - ((value - min) / range) * (height - 6) - 3;
      return `${x},${y}`;
    })
    .join(" ");
  const fillPoints = `0,${height} ${points} ${width},${height}`;
  return (
    <span className={`spark ${positive ? "spark--pos" : "spark--neg"}`}>
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true">
        <polygon points={fillPoints} />
        <polyline points={points} />
      </svg>
    </span>
  );
}

export default App;
