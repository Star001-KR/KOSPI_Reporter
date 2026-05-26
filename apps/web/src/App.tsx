import {
  ArrowRight,
  ArrowUpRight,
  Bell,
  Bookmark,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  FileText,
  GripVertical,
  Info,
  Lightbulb,
  LogOut,
  Moon,
  Paperclip,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  StickyNote,
  Sun,
  X,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import { ApiError, api } from "./api";
import {
  deviceTheme,
  loadBookmarkIds,
  loadNotes,
  loadReadIds,
  loadTheme,
  loadWatchlist,
  removeWatchlistEntry,
  saveBookmarkIds,
  saveNotes,
  saveReadIds,
  saveTheme,
  saveWatchlist,
  upsertWatchlistEntry,
  watchlistKey,
} from "./storage";
import type {
  AnalysisResult,
  AuthUser,
  DailyPrice,
  Sentiment,
  SymbolDetail,
  SymbolLookupResult,
  WatchlistEntry,
} from "./types";

type ViewName = "dashboard" | "feed";
type IssueType = "news" | "disc";
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
  unreadCount: number;
  unreadNewsCount: number;
  unreadDisclosureCount: number;
  latestCollectedAt: string | null;
  dominantSent: SentKey;
  spark: DailyPrice[];
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
  aiSummary: string | null;
  impact: string;
  rationale: string;
  keywords: string[];
  modelVersion: string;
  clusterSize: number;
  clusterSources: string[];
  relatedArticles: RelatedArticle[];
};

type RelatedArticle = {
  id: string;
  itemId: number;
  title: string;
  source: string;
  url: string;
  occurredAt: string | null;
  collectedAt: string;
  sentiment: SentKey;
  importance: number;
  summary: string;
  aiSummary: string | null;
  impact: string;
  rationale: string;
  keywords: string[];
  modelVersion: string;
  isRepresentative: boolean;
};

type FeedFilter = {
  stockCodes?: string[] | null;
  type?: IssueType | null;
  sentiment?: SentKey | null;
  minImportance?: number;
  bookmarkedOnly?: boolean;
};

type NotificationTone = "info" | "success" | "error";

type SystemNotification = {
  id: string;
  tone: NotificationTone;
  title: string;
  message: string;
  createdAt: string;
  read: boolean;
};

type NotificationInput = {
  tone: NotificationTone;
  title: string;
  message: string;
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

const NEWS_CLUSTER_WINDOW_MS = 24 * 60 * 60 * 1000;
const NEWS_TIGHT_CLUSTER_WINDOW_MS = 6 * 60 * 60 * 1000;
const NEWS_SIMILARITY_THRESHOLD = 0.62;
const NEWS_MIN_SHARED_TERMS = 2;

const NEWS_STOP_TERMS = new Set([
  "단독",
  "속보",
  "종합",
  "영상",
  "사진",
  "그래픽",
  "기자",
  "뉴스",
  "관련",
  "전망",
  "분석",
  "오늘",
  "내일",
  "회장",
  "대표",
  "삼성",
  "삼전",
]);

const NEWS_TERM_ALIASES: Array<{ term: string; pattern: RegExp }> = [
  { term: "사과", pattern: /사과|사죄|고개\s*숙|대국민\s*사과|비바람/i },
  { term: "노사", pattern: /노사|노조|사측|총파업|파업|임금|임단협|성과급|연봉|노동/i },
  { term: "교섭", pattern: /교섭|대화\s*재개|중재|요구|사후조정|중노위/i },
  { term: "귀국", pattern: /귀국|급히\s*귀국/i },
  { term: "교체", pattern: /교체|쇄신|전격\s*교체/i },
  { term: "반도체", pattern: /반도체|메모리|hbm|d램|낸드/i },
  { term: "실적", pattern: /실적|영업이익|매출|흑자|적자/i },
  { term: "계약", pattern: /계약|수주|공급|납품/i },
  { term: "규제", pattern: /규제|제재|조사|소송/i },
];

const NEWS_STRONG_EVENT_TERMS = new Set(["사과", "노사", "교섭", "귀국", "교체", "계약", "규제"]);

// How often the dashboard re-reads the DB on its own. Independent of the
// scheduler's scrape cadence — pure UI polling, no external calls.
const AUTO_REFRESH_SECONDS = 1800;

// Minimum interval between "지금 새로고침" clicks. The DB is only as fresh as
// the scheduler made it, so reading more often is wasted work; the cooldown
// also keeps a user from spamming reloads.
const MANUAL_REFRESH_COOLDOWN_SECONDS = 600;

// Per-user watchlist cap. The server's symbol table is shared across users, so
// this cap lives on the client — it bounds how many cards a single account can
// pile onto its dashboard, not the system-wide collection target set.
const MAX_WATCHLIST_SIZE = 20;

// Recent-arrival ticker: how many recent issues to cycle and how long each shows.
const RECENT_ARRIVAL_LIMIT = 6;
const RECENT_ARRIVAL_INTERVAL_MS = 5000;

// Reading-pane "묶인 뉴스" list: render this many bundled articles before
// collapsing the remainder behind an expand toggle.
const RELATED_COLLAPSE_LIMIT = 3;

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

function formatNotificationStamp(value: string): string {
  return new Intl.DateTimeFormat("ko-KR", {
    month: "2-digit",
    day: "2-digit",
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
  return "공시";
}

function naverResearchUrl(stock: Pick<ResearchStock, "code">): string {
  const params = new URLSearchParams({
    keyword: "",
    brokerCode: "",
    writeFromDate: "",
    writeToDate: "",
    searchType: "itemCode",
    itemCode: stock.code,
  });
  return `https://finance.naver.com/research/company_list.naver?${params.toString()}`;
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

function issueTime(issue: ResearchIssue): number {
  const time = new Date(issue.occurredAt ?? issue.collectedAt).getTime();
  return Number.isFinite(time) ? time : 0;
}

function uniqueValues(values: string[]): string[] {
  return Array.from(new Set(values.filter(Boolean)));
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function cleanNewsText(value: string): string {
  return value
    .normalize("NFKC")
    .replace(/<[^>]*>/g, " ")
    .replace(/&quot;|&#34;/g, '"')
    .replace(/&#39;|&apos;/g, "'")
    .replace(/&amp;/g, "&")
    .toLowerCase()
    .replace(/[“”"'‘’()[\]{}<>·,:;!?~_+*/\\|…—–-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizedNewsTitle(issue: ResearchIssue): string {
  let text = cleanNewsText(issue.title);
  const removable = uniqueValues([
    issue.stockCode,
    issue.stockName,
    issue.stockName.replace(/\s+/g, ""),
    issue.market,
  ]);
  removable.forEach((value) => {
    if (!value) return;
    text = text.replace(new RegExp(escapeRegExp(cleanNewsText(value)), "gi"), " ");
  });
  return text.replace(/\s+/g, " ").trim();
}

function newsIssueTerms(issue: ResearchIssue): Set<string> {
  const text = normalizedNewsTitle(issue);
  const terms = new Set<string>();

  text.split(/\s+/).forEach((term) => {
    const normalized = term.trim();
    if (normalized.length < 2) return;
    if (/^\d+(?:\.\d+)?(?:%|년|월|일|분기|시|분)?$/.test(normalized)) return;
    if (NEWS_STOP_TERMS.has(normalized)) return;
    terms.add(normalized);
  });

  NEWS_TERM_ALIASES.forEach(({ term, pattern }) => {
    if (pattern.test(text)) {
      terms.add(term);
    }
  });

  return terms;
}

function charShingles(value: string, size = 2): Set<string> {
  const compact = value.replace(/\s+/g, "");
  const chars = Array.from(compact);
  if (chars.length <= size) {
    return new Set(compact ? [compact] : []);
  }
  return new Set(chars.slice(0, chars.length - size + 1).map((_, index) => chars.slice(index, index + size).join("")));
}

function diceSimilarity(a: Set<string>, b: Set<string>): number {
  if (!a.size || !b.size) return 0;
  let intersection = 0;
  a.forEach((value) => {
    if (b.has(value)) intersection += 1;
  });
  return (2 * intersection) / (a.size + b.size);
}

function sharedTermCount(a: Set<string>, b: Set<string>): number {
  let count = 0;
  a.forEach((term) => {
    if (b.has(term)) count += 1;
  });
  return count;
}

function sharedStrongTermCount(a: Set<string>, b: Set<string>): number {
  let count = 0;
  NEWS_STRONG_EVENT_TERMS.forEach((term) => {
    if (a.has(term) && b.has(term)) count += 1;
  });
  return count;
}

function newsTitleSimilarity(a: ResearchIssue, b: ResearchIssue): number {
  const termsA = newsIssueTerms(a);
  const termsB = newsIssueTerms(b);
  const shared = sharedTermCount(termsA, termsB);
  const containment = shared / Math.max(1, Math.min(termsA.size, termsB.size));
  const dice = diceSimilarity(charShingles(normalizedNewsTitle(a)), charShingles(normalizedNewsTitle(b)));
  return Math.max(dice, containment);
}

function shouldClusterNews(a: ResearchIssue, b: ResearchIssue): boolean {
  if (a.id === b.id || a.type !== "news" || b.type !== "news") return false;
  if (a.stockCode !== b.stockCode) return false;

  const gap = Math.abs(issueTime(a) - issueTime(b));
  if (gap > NEWS_CLUSTER_WINDOW_MS) return false;

  const termsA = newsIssueTerms(a);
  const termsB = newsIssueTerms(b);
  const shared = sharedTermCount(termsA, termsB);
  const strongShared = sharedStrongTermCount(termsA, termsB);
  const similarity = newsTitleSimilarity(a, b);

  if (strongShared >= 2) return true;
  if (strongShared >= 1 && shared >= NEWS_MIN_SHARED_TERMS && similarity >= 0.28) return true;
  if (strongShared >= 1 && gap <= NEWS_TIGHT_CLUSTER_WINDOW_MS && similarity >= 0.18) return true;
  return shared >= NEWS_MIN_SHARED_TERMS && similarity >= NEWS_SIMILARITY_THRESHOLD;
}

function relatedArticleFromIssue(issue: ResearchIssue, isRepresentative = false): RelatedArticle {
  return {
    id: issue.id,
    itemId: issue.itemId,
    title: issue.title,
    source: issue.source,
    url: issue.url,
    occurredAt: issue.occurredAt,
    collectedAt: issue.collectedAt,
    sentiment: issue.sentiment,
    importance: issue.importance,
    summary: issue.summary,
    aiSummary: issue.aiSummary,
    impact: issue.impact,
    rationale: issue.rationale,
    keywords: issue.keywords,
    modelVersion: issue.modelVersion,
    isRepresentative,
  };
}

function aggregateClusterSentiment(cluster: ResearchIssue[], representative: ResearchIssue): SentKey {
  const scores = cluster.reduce(
    (acc, issue) => {
      acc[issue.sentiment] += issue.importance + 1;
      return acc;
    },
    { pos: 0, neg: 0, neu: 0 } satisfies Record<SentKey, number>,
  );
  const best = (Object.keys(scores) as SentKey[]).reduce((winner, sentiment) =>
    scores[sentiment] > scores[winner] ? sentiment : winner,
  );
  return scores[best] > 0 ? best : representative.sentiment;
}

function representativeScore(issue: ResearchIssue, cluster: ResearchIssue[]): number {
  const titleLength = Array.from(issue.title).length;
  const isTruncated = /\.{2,}|…/.test(issue.title);
  const terms = newsIssueTerms(issue);
  const centrality =
    cluster.length <= 1
      ? 1
      : cluster
          .filter((candidate) => candidate.id !== issue.id)
          .reduce((sum, candidate) => sum + newsTitleSimilarity(issue, candidate), 0) /
        Math.max(1, cluster.length - 1);
  const hasSummary = issue.summary.trim() && !issue.summary.includes("대기 중");
  const hasUrl = Boolean(issue.url);
  const newest = Math.max(...cluster.map(issueTime));
  const oldest = Math.min(...cluster.map(issueTime));
  const recency = newest === oldest ? 1 : (issueTime(issue) - oldest) / (newest - oldest);
  const readableTitle =
    (titleLength >= 18 ? 4 : 0) +
    (titleLength <= 96 ? 3 : 0) +
    (isTruncated ? -6 : 3) +
    Math.min(terms.size, 8) * 0.4;

  return (
    issue.importance * 16 +
    readableTitle * 2 +
    centrality * 18 +
    (hasSummary ? 5 : 0) +
    (hasUrl ? 3 : 0) +
    recency
  );
}

function pickRepresentative(cluster: ResearchIssue[]): ResearchIssue {
  return cluster.reduce((best, issue) =>
    representativeScore(issue, cluster) > representativeScore(best, cluster) ? issue : best,
  );
}

function buildClusterIssue(cluster: ResearchIssue[]): ResearchIssue {
  if (cluster.length === 1) {
    const issue = cluster[0];
    return {
      ...issue,
      clusterSize: 1,
      clusterSources: uniqueValues([issue.source]),
      relatedArticles: [relatedArticleFromIssue(issue, true)],
    };
  }

  const sorted = [...cluster].sort((a, b) => issueTime(b) - issueTime(a));
  const representative = pickRepresentative(sorted);
  const clusterSources = uniqueValues(sorted.map((issue) => issue.source));
  const relatedArticles = sorted.map((issue) => relatedArticleFromIssue(issue, issue.id === representative.id));
  // The cluster id is its founding article — the member with the smallest
  // itemId. itemId is monotonic, so later-collected articles never displace
  // it: the id holds steady as related articles arrive, keeping read state
  // and bookmarks attached. A preferred stock and its common stock cluster
  // the same articles, so they share one founding article — and one id.
  const founding = sorted.reduce((earliest, issue) =>
    issue.itemId < earliest.itemId ? issue : earliest,
  );

  return {
    ...representative,
    id: founding.id,
    occurredAt: sorted[0].occurredAt,
    collectedAt: sorted[0].collectedAt,
    sentiment: aggregateClusterSentiment(sorted, representative),
    importance: Math.max(...sorted.map((issue) => issue.importance)),
    keywords: uniqueValues(sorted.flatMap((issue) => issue.keywords)).slice(0, 5),
    clusterSize: sorted.length,
    clusterSources,
    relatedArticles,
  };
}

function clusterNewsIssues(issues: ResearchIssue[]): ResearchIssue[] {
  const news = issues.filter((issue) => issue.type === "news").sort((a, b) => issueTime(b) - issueTime(a));
  const nonNews = issues.filter((issue) => issue.type !== "news");
  const clusters: ResearchIssue[][] = [];

  news.forEach((issue) => {
    const matches = clusters.filter((cluster) => cluster.some((member) => shouldClusterNews(issue, member)));
    if (!matches.length) {
      clusters.push([issue]);
      return;
    }

    const primary = matches[0];
    primary.push(issue);
    matches.slice(1).forEach((cluster) => {
      primary.push(...cluster);
      clusters.splice(clusters.indexOf(cluster), 1);
    });
  });

  return [...nonNews, ...clusters.map(buildClusterIssue)].sort((a, b) => issueTime(b) - issueTime(a));
}

function buildIssues(details: SymbolDetail[]): ResearchIssue[] {
  const issues = details.flatMap((detail) => {
    const news = detail.news_items.map(({ item, analysis }) => {
      const issue: ResearchIssue = {
        id: `news-${item.id}`,
        itemId: item.id,
        stockId: detail.id,
        stockCode: detail.code,
        stockName: detail.name,
        market: detail.market,
        type: "news",
        source: item.source ?? "News",
        title: item.title,
        url: item.original_url,
        occurredAt: item.published_at ?? item.collected_at,
        collectedAt: item.collected_at,
        sentiment: toSentKey(analysis?.sentiment),
        importance: analysis?.importance ?? 0,
        summary: analysis?.summary ?? item.summary ?? "요약 대기 중입니다.",
        aiSummary: item.ai_summary,
        impact: analysis?.portfolio_impact ?? "포트폴리오 영향 분석 대기 중입니다.",
        rationale: analysis?.rationale ?? "분석 근거가 아직 생성되지 않았습니다.",
        keywords: analysisKeywords(analysis),
        modelVersion: analysis?.model_version ?? "v2.1",
        clusterSize: 1,
        clusterSources: [item.source ?? "News"],
        relatedArticles: [],
      };
      return { ...issue, relatedArticles: [relatedArticleFromIssue(issue, true)] };
    });
    const disclosures = detail.disclosures.map(({ item, analysis }) => {
      const issue: ResearchIssue = {
        id: `disc-${item.id}`,
        itemId: item.id,
        stockId: detail.id,
        stockCode: detail.code,
        stockName: detail.name,
        market: detail.market,
        type: "disc",
        source: "DART",
        title: item.report_name,
        url: item.original_url,
        occurredAt: item.submitted_at ?? item.collected_at,
        collectedAt: item.collected_at,
        sentiment: toSentKey(analysis?.sentiment),
        importance: analysis?.importance ?? 0,
        summary: analysis?.summary ?? `${item.report_name} 공시가 수집되었습니다.`,
        aiSummary: null,
        impact: analysis?.portfolio_impact ?? "공시 영향 분석 대기 중입니다.",
        rationale: analysis?.rationale ?? `접수번호 ${item.rcept_no}`,
        keywords: analysisKeywords(analysis),
        modelVersion: analysis?.model_version ?? "v2.1",
        clusterSize: 1,
        clusterSources: ["DART"],
        relatedArticles: [],
      };
      return { ...issue, relatedArticles: [relatedArticleFromIssue(issue, true)] };
    });
    return [...news, ...disclosures];
  });

  return clusterNewsIssues(issues);
}

function latestCollectedFromDetail(detail: SymbolDetail | undefined): string | null {
  if (!detail) return null;
  const stamps = [
    ...detail.news_items.map((entry) => entry.item.collected_at),
    ...detail.disclosures.map((entry) => entry.item.collected_at),
  ];
  if (!stamps.length) return null;
  return stamps.reduce((latest, value) => (value > latest ? value : latest));
}

function buildStocks(
  watchlist: WatchlistEntry[],
  details: SymbolDetail[],
  issues: ResearchIssue[],
  pricesBySymbol: Record<number, DailyPrice[]>,
  readIds: Set<string>,
): ResearchStock[] {
  const detailByKey = new Map(
    details.map((detail) => [`${detail.market}:${detail.code}`, detail]),
  );
  return watchlist.map((entry, index) => {
    const detail = detailByKey.get(`${entry.market}:${entry.code}`);
    const id = detail?.id ?? -(index + 1);
    const quantity = entry.quantity;
    const averageCost = entry.averageCost;
    const spark = detail ? pricesBySymbol[detail.id] ?? [] : [];
    // Current price and day-over-day change come from the daily close series.
    const latestClose = spark.length > 0 ? spark[spark.length - 1].close : null;
    const prevClose = spark.length > 1 ? spark[spark.length - 2].close : null;
    const price = latestClose ?? 0;
    const changePct =
      latestClose !== null && prevClose !== null && prevClose !== 0
        ? ((latestClose - prevClose) / prevClose) * 100
        : 0;
    // Valuation needs the holding (quantity / average cost) and the live price.
    let marketValue = 0;
    let profitLoss = 0;
    let profitLossPct = 0;
    if (quantity !== null) {
      if (latestClose !== null) {
        marketValue = quantity * latestClose;
      } else if (averageCost !== null) {
        marketValue = quantity * averageCost;
      }
      if (averageCost !== null && latestClose !== null) {
        const costBasis = quantity * averageCost;
        profitLoss = quantity * (latestClose - averageCost);
        profitLossPct = costBasis !== 0 ? (profitLoss / costBasis) * 100 : 0;
      }
    }
    const stockIssues = issues.filter((issue) => issue.stockId === id);
    const unreadIssues = stockIssues.filter((issue) => !readIds.has(issue.id));
    const unreadCount = unreadIssues.length;
    const unreadNewsCount = unreadIssues.filter((issue) => issue.type === "news").length;
    const unreadDisclosureCount = unreadIssues.filter((issue) => issue.type === "disc").length;
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
    return {
      id,
      code: entry.code,
      name: entry.name,
      market: entry.market,
      quantity,
      averageCost,
      marketValue,
      price,
      changePct,
      profitLoss,
      profitLossPct,
      unreadCount,
      unreadNewsCount,
      unreadDisclosureCount,
      latestCollectedAt: latestCollectedFromDetail(detail),
      dominantSent,
      spark,
    };
  });
}

function watchlistEntryFromRegistration(state: RegisterState): WatchlistEntry {
  return {
    market: state.selected?.market ?? "KOSPI",
    code: state.selected?.code ?? state.query,
    name: state.selected?.name ?? "",
    quantity: numberOrNull(state.quantity),
    averageCost: numberOrNull(state.averageCost),
    memo: state.memo.trim() || null,
  };
}

function App() {
  const [view, setView] = useState<ViewName>("dashboard");
  const [watchlist, setWatchlist] = useState<WatchlistEntry[]>([]);
  const [details, setDetails] = useState<SymbolDetail[]>([]);
  const [pricesBySymbol, setPricesBySymbol] = useState<Record<number, DailyPrice[]>>({});
  const [selectedIssueId, setSelectedIssueId] = useState<string | null>(null);
  const [filter, setFilter] = useState<FeedFilter>({});
  const [modalOpen, setModalOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [notifications, setNotifications] = useState<SystemNotification[]>([]);
  const [theme, setTheme] = useState<"light" | "dark">(deviceTheme);
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isBusy, setIsBusy] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState(AUTO_REFRESH_SECONDS);
  const [manualCooldownSeconds, setManualCooldownSeconds] = useState(0);
  const [readIds, setReadIds] = useState<Set<string>>(new Set());
  const [bookmarkIds, setBookmarkIds] = useState<Set<string>>(new Set());
  const [notes, setNotes] = useState<Record<string, string>>({});

  const markRead = useCallback((id: string) => {
    if (!authUser) return;
    const scope = String(authUser.id);
    setReadIds((prev) => {
      if (prev.has(id)) return prev;
      const next = new Set(prev);
      next.add(id);
      saveReadIds(scope, next);
      return next;
    });
  }, [authUser]);

  const toggleBookmark = useCallback((id: string) => {
    if (!authUser) return;
    const scope = String(authUser.id);
    setBookmarkIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      saveBookmarkIds(scope, next);
      return next;
    });
  }, [authUser]);

  const saveIssueNote = useCallback((id: string, text: string) => {
    if (!authUser) return;
    const scope = String(authUser.id);
    setNotes((prev) => {
      const next = { ...prev };
      if (text) next[id] = text;
      else delete next[id];
      saveNotes(scope, next);
      return next;
    });
  }, [authUser]);

  const pushNotification = useCallback((input: NotificationInput) => {
    const createdAt = new Date().toISOString();
    const id = `${createdAt}-${Math.random().toString(36).slice(2, 8)}`;
    setNotifications((items) => [
      { ...input, id, createdAt, read: false },
      ...items,
    ].slice(0, 30));
  }, []);

  const unreadNotificationCount = useMemo(
    () => notifications.filter((notification) => !notification.read).length,
    [notifications],
  );

  function toggleNotifications() {
    const nextOpen = !notificationsOpen;
    setNotificationsOpen(nextOpen);
    if (nextOpen) {
      setNotifications((items) => items.map((item) => ({ ...item, read: true })));
    }
  }

  function clearNotifications() {
    setNotifications([]);
  }

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    document.documentElement.setAttribute("data-accent", "ink");
  }, [theme]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const loginError = params.get("auth_error");
    if (loginError) {
      setAuthError("Google 로그인에 실패했습니다. 잠시 후 다시 시도해 주세요.");
      window.history.replaceState({}, document.title, window.location.pathname);
    } else if (params.get("auth")) {
      window.history.replaceState({}, document.title, window.location.pathname);
    }

    api
      .getMe()
      .then((user) => {
        setAuthUser(user);
        setAuthError(null);
      })
      .catch(() => {
        setAuthUser(null);
      })
      .finally(() => setAuthLoading(false));
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setSecondsLeft((value) => (value <= 0 ? AUTO_REFRESH_SECONDS : value - 1));
      setManualCooldownSeconds((value) => Math.max(0, value - 1));
    }, 1000);
    return () => window.clearInterval(timer);
  }, []);

  const countdown = useMemo(() => {
    const minutes = Math.floor(secondsLeft / 60);
    const seconds = secondsLeft % 60;
    return `${minutes}:${String(seconds).padStart(2, "0")}`;
  }, [secondsLeft]);

  const manualCooldown = useMemo(() => {
    if (manualCooldownSeconds <= 0) return null;
    const minutes = Math.floor(manualCooldownSeconds / 60);
    const seconds = manualCooldownSeconds % 60;
    return `${minutes}:${String(seconds).padStart(2, "0")}`;
  }, [manualCooldownSeconds]);

  const watchedDetails = useMemo(() => {
    const keys = new Set(watchlist.map((entry) => watchlistKey(entry)));
    return details.filter((detail) => keys.has(watchlistKey(detail)));
  }, [watchlist, details]);
  const issues = useMemo(() => buildIssues(watchedDetails), [watchedDetails]);
  const stocks = useMemo(
    () => buildStocks(watchlist, watchedDetails, issues, pricesBySymbol, readIds),
    [watchlist, watchedDetails, issues, pricesBySymbol, readIds],
  );
  const registeredCodes = useMemo(
    () => watchlist.map((entry) => entry.code),
    [watchlist],
  );

  const refresh = useCallback(async () => {
    // The server holds only the shared public collection universe.
    const serverSymbols = await api.listSymbols();
    const nextDetails = await Promise.all(
      serverSymbols.map((symbol) => api.getSymbol(symbol.id)),
    );
    setDetails(nextDetails);
  }, []);

  // Lazy AI summary for a news item that was not summarized eagerly at
  // collection time. The server caches the result, so this only spends tokens
  // on the first read; the response is merged into the loaded details so the
  // reading pane re-renders with the new summary. The promise resolves either
  // way so the caller can clear its "loading" mark — the UI just falls back
  // to the rule-based summary on failure or when no key is configured.
  const requestNewsAiSummary = useCallback(async (newsItemId: number) => {
    try {
      const updated = await api.generateNewsAiSummary(newsItemId);
      setDetails((prev) =>
        prev.map((detail) => {
          const hasItem = detail.news_items.some(
            (entry) => entry.item.id === newsItemId,
          );
          if (!hasItem) return detail;
          return {
            ...detail,
            news_items: detail.news_items.map((entry) =>
              entry.item.id === newsItemId ? { ...entry, item: updated } : entry,
            ),
          };
        }),
      );
    } catch {
      // Stay silent — the UI keeps showing the rule-based fallback.
    }
  }, []);

  // When the auto-countdown reaches zero, do exactly one DB re-poll. The
  // interval above wraps secondsLeft back to AUTO_REFRESH_SECONDS on the next
  // tick, so this effect fires once per cycle, not continuously.
  useEffect(() => {
    if (secondsLeft !== 0) return;
    refresh().catch(() => {
      // A read failure is already surfaced by the next user-triggered refresh
      // or the dashboard-load error path; do not double-notify here.
    });
  }, [secondsLeft, refresh]);

  useEffect(() => {
    if (!authUser) {
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    refresh()
      .catch((err: Error) =>
        pushNotification({
          tone: "error",
          title: "초기 데이터 로드 실패",
          message: err.message,
        }),
      )
      .finally(() => setIsLoading(false));
  }, [refresh, pushNotification, authUser]);

  // The watchlist, holdings and read state live in this browser, scoped to the
  // signed-in account: load this account's data on sign-in and drop it on
  // sign-out so a shared browser never leaks data across accounts.
  useEffect(() => {
    if (!authUser) {
      setWatchlist([]);
      setReadIds(new Set());
      setBookmarkIds(new Set());
      setNotes({});
      // Feed view state isn't account data, but a stale filter must not outlive
      // a sign-out — it would silently empty the next account's feed.
      setFilter({});
      setSelectedIssueId(null);
      return;
    }
    const scope = String(authUser.id);
    setWatchlist(loadWatchlist(scope));
    setReadIds(loadReadIds(scope));
    setBookmarkIds(loadBookmarkIds(scope));
    setNotes(loadNotes(scope));
    // Theme is a display preference, not private data, so it is restored on
    // sign-in but left untouched on sign-out (no flash back to light).
    setTheme(loadTheme(scope));
  }, [authUser]);

  // Load real daily closes for each symbol once details arrive; a per-symbol
  // failure just yields an empty series so the rest of the dashboard is fine.
  useEffect(() => {
    if (details.length === 0) return;
    let cancelled = false;
    Promise.all(
      details.map((detail) =>
        api
          .getSymbolPrices(detail.id)
          .then((rows) => [detail.id, rows] as const)
          .catch(() => [detail.id, [] as DailyPrice[]] as const),
      ),
    ).then((entries) => {
      if (cancelled) return;
      const next: Record<number, DailyPrice[]> = {};
      for (const [id, rows] of entries) next[id] = rows;
      setPricesBySymbol(next);
    });
    return () => {
      cancelled = true;
    };
  }, [details]);

  useEffect(() => {
    if (!issues.length && selectedIssueId) {
      setSelectedIssueId(null);
      return;
    }
    if (!selectedIssueId && issues.length) {
      setSelectedIssueId(issues[0].id);
    }
    if (selectedIssueId && issues.length && !issues.some((issue) => issue.id === selectedIssueId)) {
      setSelectedIssueId(issues[0].id);
    }
  }, [issues, selectedIssueId]);

  async function runAction(
    action: () => Promise<void>,
    options?: {
      start?: NotificationInput;
      errorTitle?: string;
    },
  ) {
    setIsBusy(true);
    if (options?.start) {
      pushNotification(options.start);
    }
    try {
      await action();
    } catch (err) {
      pushNotification({
        tone: "error",
        title: options?.errorTitle ?? "작업 실패",
        message: err instanceof Error ? err.message : "작업에 실패했습니다.",
      });
    } finally {
      setIsBusy(false);
    }
  }

  async function handleRefreshCollection() {
    // External scraping (Naver, OpenDart) is owned by the background scheduler
    // — the user-facing refresh just re-reads the DB so a click never spikes
    // outbound API usage or blocks on a slow upstream. The cooldown caps how
    // often a user can poke this; the DB cannot be fresher than the scheduler
    // made it.
    if (manualCooldownSeconds > 0) return;
    await runAction(async () => {
      await refresh();
      setSecondsLeft(AUTO_REFRESH_SECONDS);
      setManualCooldownSeconds(MANUAL_REFRESH_COOLDOWN_SECONDS);
      pushNotification({
        tone: "success",
        title: "데이터 갱신",
        message: "최신 수집 내역을 대시보드에 반영했습니다.",
      });
    }, {
      errorTitle: "데이터 갱신 실패",
    });
  }

  async function handleRegister(state: RegisterState) {
    await runAction(async () => {
      if (!authUser) return;
      const scope = String(authUser.id);
      const entry = watchlistEntryFromRegistration(state);
      // Per-user cap on the local watchlist: re-adding an existing entry is
      // always fine (it just refreshes metadata); only a genuinely new entry
      // counts toward the limit.
      const currentWatchlist = loadWatchlist(scope);
      const alreadyInWatchlist = currentWatchlist.some(
        (item) => item.market === entry.market && item.code === entry.code,
      );
      if (
        !alreadyInWatchlist &&
        currentWatchlist.length >= MAX_WATCHLIST_SIZE
      ) {
        pushNotification({
          tone: "error",
          title: "종목 등록 불가",
          message: `대시보드 가독성을 위해 종목은 최대 ${MAX_WATCHLIST_SIZE}개까지 등록할 수 있습니다.`,
        });
        return;
      }
      // Register the symbol as a shared collection target — identity only, no
      // holdings ever leave the browser. A 409 means it already exists, which
      // is fine; any other failure means the server did not register it.
      let serverRegistered = true;
      try {
        await api.createSymbol({
          market: entry.market,
          code: entry.code,
          name: entry.name,
          memo: null,
          holding: null,
        });
      } catch (err) {
        if (!(err instanceof ApiError && err.status === 409)) {
          serverRegistered = false;
        }
      }
      const nextWatchlist = upsertWatchlistEntry(currentWatchlist, entry);
      saveWatchlist(scope, nextWatchlist);
      setWatchlist(nextWatchlist);
      await refresh();
      setView("dashboard");
      pushNotification(
        serverRegistered
          ? {
              tone: "success",
              title: "종목 추가 완료",
              message: `${entry.name} 종목이 대시보드에 추가되었습니다.`,
            }
          : {
              tone: "error",
              title: "서버 등록 실패",
              message: `${entry.name}을(를) 관심종목에 추가했지만 서버 수집 등록에 실패했습니다. 잠시 후 다시 시도해 주세요.`,
            },
      );
    }, {
      errorTitle: "종목 추가 실패",
    });
  }

  async function handleLogout() {
    await runAction(async () => {
      await api.logout();
      setAuthUser(null);
      setNotifications([]);
      setView("dashboard");
    }, {
      errorTitle: "로그아웃 실패",
    });
  }

  // The recent-arrival card passes the issue it is showing so the feed opens
  // with that exact item selected, not just the stock filtered.
  function goToFeed(stockCode?: string, issueId?: string) {
    setFilter(stockCode ? { stockCodes: [stockCode] } : {});
    setSelectedIssueId(issueId ?? null);
    setView("feed");
  }

  // Reorder watchlist entries (and persist) for hand-sorted dashboard cards;
  // card order mirrors watchlist order through buildStocks.
  function reorderWatchlist(fromIndex: number, toIndex: number) {
    if (
      fromIndex === toIndex ||
      fromIndex < 0 ||
      toIndex < 0 ||
      fromIndex >= watchlist.length ||
      toIndex >= watchlist.length
    ) {
      return;
    }
    const next = [...watchlist];
    const [moved] = next.splice(fromIndex, 1);
    next.splice(toIndex, 0, moved);
    setWatchlist(next);
    if (authUser) saveWatchlist(String(authUser.id), next);
  }

  // Drop a card from the dashboard. The watchlist lives only in this browser,
  // so removal just prunes localStorage; the shared public symbol is untouched.
  function removeFromWatchlist(stock: ResearchStock) {
    const next = removeWatchlistEntry(watchlist, {
      market: stock.market,
      code: stock.code,
    });
    setWatchlist(next);
    if (authUser) saveWatchlist(String(authUser.id), next);
    pushNotification({
      tone: "info",
      title: "종목 제거",
      message: `${stock.name} 카드를 대시보드에서 제거했습니다.`,
    });
  }

  const watchlistEmpty = !isLoading && watchlist.length === 0;

  if (authLoading) {
    return <LoginGate mode="checking" error={authError} />;
  }

  if (!authUser) {
    return <LoginGate mode="login" error={authError} />;
  }

  return (
    <div className="app">
      <AppBar
        view={view}
        setView={setView}
        countdown={countdown}
        refreshing={isBusy}
        manualCooldown={manualCooldown}
        onRefresh={handleRefreshCollection}
        onAddStock={() => setModalOpen(true)}
        notifications={notifications}
        notificationsOpen={notificationsOpen}
        unreadNotificationCount={unreadNotificationCount}
        onToggleNotifications={toggleNotifications}
        onCloseNotifications={() => setNotificationsOpen(false)}
        onClearNotifications={clearNotifications}
        theme={theme}
        setTheme={setTheme}
        user={authUser}
        onLogout={handleLogout}
      />

      <main className="app-main">
        {view === "dashboard" ? (
          watchlistEmpty ? (
            <EmptyState onAddStock={() => setModalOpen(true)} />
          ) : (
            <Dashboard
              stocks={stocks}
              issues={issues}
              countdown={countdown}
              refreshing={isBusy}
              manualCooldown={manualCooldown}
              onRefresh={handleRefreshCollection}
              onReorder={reorderWatchlist}
              onRemove={removeFromWatchlist}
              onPlanetClick={(stock, issueId) => goToFeed(stock.code, issueId)}
            />
          )
        ) : (
          <Feed
            stocks={stocks}
            issues={issues}
            filter={filter}
            setFilter={setFilter}
            selectedIssueId={selectedIssueId}
            setSelectedIssueId={setSelectedIssueId}
            readIds={readIds}
            markRead={markRead}
            bookmarkIds={bookmarkIds}
            toggleBookmark={toggleBookmark}
            notes={notes}
            saveIssueNote={saveIssueNote}
            onRequestAiSummary={requestNewsAiSummary}
          />
        )}
      </main>

      <AdSlot slot="page-bottom" />

      <footer className="app-footer">
        <strong>KOSPI Reporter</strong> — OpenDART 공시와 Naver 뉴스를 수집·요약해
        제공하는 정보 서비스입니다. 투자 조언이 아니며, 투자 판단과 그 결과의
        책임은 이용자 본인에게 있습니다.
      </footer>

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

function LoginGate({
  mode,
  error,
}: {
  mode: "checking" | "login";
  error: string | null;
}) {
  const isChecking = mode === "checking";
  return (
    <div className="login-shell">
      <section className="login-panel" aria-live="polite">
        <div className="login-mark">k</div>
        <div>
          <p className="login-eyebrow">KOSPI Reporter</p>
          <h1>{isChecking ? "로그인 상태 확인 중" : "로그인이 필요합니다"}</h1>
          <p>
            Google 계정으로 로그인하면 같은 브라우저에서 다시 접속할 때
            로그인 상태가 유지됩니다.
          </p>
        </div>
        {error && <div className="login-error">{error}</div>}
        {isChecking ? (
          <div className="login-loading">
            <RefreshCw size={15} className="spin" />
            세션 확인 중
          </div>
        ) : (
          <a className="google-login-btn" href={api.googleLoginUrl()}>
            <GoogleLogo />
            Google로 로그인
          </a>
        )}
      </section>
    </div>
  );
}

function GoogleLogo() {
  return (
    <svg
      className="google-login-icon"
      viewBox="0 0 18 18"
      aria-hidden="true"
      focusable="false"
    >
      <path
        fill="#4285F4"
        d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.91c1.7-1.57 2.69-3.88 2.69-6.62z"
      />
      <path
        fill="#34A853"
        d="M9 18c2.43 0 4.47-.81 5.96-2.18l-2.91-2.26c-.81.54-1.84.86-3.05.86-2.34 0-4.33-1.58-5.04-3.71H.96v2.33A9 9 0 0 0 9 18z"
      />
      <path
        fill="#FBBC05"
        d="M3.96 10.71A5.41 5.41 0 0 1 3.68 9c0-.59.1-1.17.28-1.71V4.96H.96A9 9 0 0 0 0 9c0 1.45.35 2.83.96 4.04l3-2.33z"
      />
      <path
        fill="#EA4335"
        d="M9 3.58c1.32 0 2.51.45 3.44 1.35l2.58-2.58C13.46.89 11.43 0 9 0A9 9 0 0 0 .96 4.96l3 2.33C4.67 5.17 6.66 3.58 9 3.58z"
      />
    </svg>
  );
}

function AppBar({
  view,
  setView,
  countdown,
  refreshing,
  manualCooldown,
  onRefresh,
  onAddStock,
  notifications,
  notificationsOpen,
  unreadNotificationCount,
  onToggleNotifications,
  onCloseNotifications,
  onClearNotifications,
  theme,
  setTheme,
  user,
  onLogout,
}: {
  view: ViewName;
  setView: (view: ViewName) => void;
  countdown: string;
  refreshing: boolean;
  manualCooldown: string | null;
  onRefresh: () => void;
  onAddStock: () => void;
  notifications: SystemNotification[];
  notificationsOpen: boolean;
  unreadNotificationCount: number;
  onToggleNotifications: () => void;
  onCloseNotifications: () => void;
  onClearNotifications: () => void;
  theme: "light" | "dark";
  setTheme: (theme: "light" | "dark") => void;
  user: AuthUser;
  onLogout: () => void;
}) {
  const userLabel = user.display_name || user.email || "로그인 사용자";
  const avatarInitial = userLabel.trim().charAt(0).toUpperCase() || "U";
  return (
    <header className="app-bar">
      <button type="button" className="logo" onClick={() => setView("dashboard")}>
        <span className="logo-mark">k</span>
        <span>KOSPI Reporter</span>
      </button>
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
        <button
          className="status-pill"
          onClick={onRefresh}
          disabled={refreshing || manualCooldown !== null}
          title={
            manualCooldown
              ? `${manualCooldown} 후 다시 새로고침할 수 있습니다`
              : "지금 새로고침"
          }
        >
          <span className="pulse" />
          <span>
            다음 수집 <b className="mono">{countdown}</b>
          </span>
          <RefreshCw size={13} className={refreshing ? "spin" : ""} />
        </button>
        <NotificationCenter
          notifications={notifications}
          open={notificationsOpen}
          unreadCount={unreadNotificationCount}
          onToggle={onToggleNotifications}
          onClose={onCloseNotifications}
          onClear={onClearNotifications}
        />
        <Button variant="primary" size="sm" icon={<Plus size={14} />} onClick={onAddStock}>
          종목 추가
        </Button>
        <div className="account-pill" title={user.email ?? userLabel}>
          {user.avatar_url ? (
            <img src={user.avatar_url} alt="" />
          ) : (
            <span className="account-avatar-fallback">{avatarInitial}</span>
          )}
          <span>{userLabel}</span>
        </div>
        <IconButton title="로그아웃" onClick={onLogout}>
          <LogOut size={17} />
        </IconButton>
        <IconButton
          title={theme === "dark" ? "라이트 모드" : "다크 모드"}
          onClick={() => {
            const next = theme === "dark" ? "light" : "dark";
            setTheme(next);
            saveTheme(String(user.id), next);
          }}
        >
          {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
        </IconButton>
      </div>
    </header>
  );
}

function NotificationCenter({
  notifications,
  open,
  unreadCount,
  onToggle,
  onClose,
  onClear,
}: {
  notifications: SystemNotification[];
  open: boolean;
  unreadCount: number;
  onToggle: () => void;
  onClose: () => void;
  onClear: () => void;
}) {
  return (
    <div className="notification-center">
      <button
        type="button"
        className={`icon-btn notification-trigger ${unreadCount > 0 ? "notification-trigger--unread" : ""}`}
        aria-label={`시스템 알림${unreadCount > 0 ? ` ${unreadCount}개 읽지 않음` : ""}`}
        aria-expanded={open}
        onClick={onToggle}
        title="시스템 알림"
      >
        <Bell size={17} />
        {unreadCount > 0 && <span className="notification-dot" />}
      </button>
      {open && (
        <div className="notification-panel" role="dialog" aria-label="시스템 알림">
          <div className="notification-head">
            <div>
              <strong>시스템 알림</strong>
              <span>{notifications.length ? `${notifications.length}개 기록` : "새 기록 없음"}</span>
            </div>
            <div className="notification-head-actions">
              {notifications.length > 0 && (
                <button type="button" onClick={onClear}>
                  모두 지우기
                </button>
              )}
              <button type="button" className="icon-btn notification-close" onClick={onClose} title="닫기">
                <X size={14} />
              </button>
            </div>
          </div>
          <div className="notification-list" aria-live="polite">
            {notifications.length === 0 ? (
              <div className="notification-empty">아직 표시할 알림이 없습니다.</div>
            ) : (
              notifications.map((notification) => (
                <div
                  key={notification.id}
                  className={`notification-item notification-item--${notification.tone}`}
                >
                  <span className="notification-mark" />
                  <div>
                    <div className="notification-item-head">
                      <strong>{notification.title}</strong>
                      <time>{formatNotificationStamp(notification.createdAt)}</time>
                    </div>
                    <p>{notification.message}</p>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Dashboard({
  stocks,
  issues,
  countdown,
  refreshing,
  manualCooldown,
  onRefresh,
  onReorder,
  onRemove,
  onPlanetClick,
}: {
  stocks: ResearchStock[];
  issues: ResearchIssue[];
  countdown: string;
  refreshing: boolean;
  manualCooldown: string | null;
  onRefresh: () => void;
  onReorder: (fromIndex: number, toIndex: number) => void;
  onRemove: (stock: ResearchStock) => void;
  onPlanetClick: (stock: ResearchStock, issueId?: string) => void;
}) {
  return (
    <div className="dashboard">
      <CollectionPane
        stocks={stocks}
        issues={issues}
        countdown={countdown}
        refreshing={refreshing}
        manualCooldown={manualCooldown}
        onRefresh={onRefresh}
        onPlanetClick={onPlanetClick}
      />
      <HoldingsPane
        stocks={stocks}
        onOpen={onPlanetClick}
        onReorder={onReorder}
        onRemove={onRemove}
      />
    </div>
  );
}

function CollectionPane({
  stocks,
  issues,
  countdown,
  refreshing,
  manualCooldown,
  onRefresh,
  onPlanetClick,
}: {
  stocks: ResearchStock[];
  issues: ResearchIssue[];
  countdown: string;
  refreshing: boolean;
  manualCooldown: string | null;
  onRefresh: () => void;
  onPlanetClick: (stock: ResearchStock, issueId?: string) => void;
}) {
  const recentItems = useMemo(
    () => issues.slice(0, RECENT_ARRIVAL_LIMIT),
    [issues],
  );
  const [recentIndex, setRecentIndex] = useState(0);

  // Snap back to the newest arrival whenever the collected set changes.
  useEffect(() => {
    setRecentIndex(0);
  }, [recentItems]);

  // Rotate through recent arrivals; a manual step restarts the dwell timer.
  useEffect(() => {
    if (recentItems.length <= 1) return;
    const timer = window.setInterval(() => {
      setRecentIndex((index) => (index + 1) % recentItems.length);
    }, RECENT_ARRIVAL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [recentItems.length, recentIndex]);

  const recentSafeIndex = recentItems.length
    ? Math.min(recentIndex, recentItems.length - 1)
    : 0;
  const recent = recentItems[recentSafeIndex] ?? null;
  const recentStock = recent
    ? stocks.find((stock) => stock.code === recent.stockCode)
    : null;

  function stepRecent(delta: number) {
    setRecentIndex((index) => {
      const len = recentItems.length;
      if (len <= 0) return 0;
      return (((index + delta) % len) + len) % len;
    });
  }
  const totalNew = stocks.reduce((sum, stock) => sum + stock.unreadCount, 0);
  const lastCollected = issues.reduce<string | null>(
    (latest, issue) =>
      !latest || issue.collectedAt > latest ? issue.collectedAt : latest,
    null,
  );
  return (
    <section className="dash-pane dash-pane--left">
      <div className="dash-pane-head">
        <h2>수집 · 자료</h2>
        <span className="meta">마지막 {formatDate(lastCollected)} · 자동 {AUTO_REFRESH_SECONDS / 60}분</span>
      </div>
      <Orbital
        stocks={stocks}
        countdown={countdown}
        onRefresh={onRefresh}
        refreshing={refreshing}
        manualCooldown={manualCooldown}
        onPlanetClick={onPlanetClick}
      />
      <div className="orbital-foot">
        <span>
          <b>{totalNew}건</b> 새 정보
        </span>
        <span>수집 항목 {issues.length}건</span>
      </div>
      {recent && recentStock && (
        <div className="recent-arrival">
          <button
            type="button"
            key={recent.id}
            className="recent-arrival-main"
            onClick={() => onPlanetClick(recentStock, recent.id)}
          >
            <span className="meta">최근 도착</span>
            <span className="when soft">{formatTime(recent.occurredAt)}</span>
            <SentGlyph sentiment={recent.sentiment} />
            <span className="recent-stock">{recentStock.name}</span>
            <span className="recent-title">· {recent.title}</span>
          </button>
          <div className="recent-arrival-nav">
            <button
              type="button"
              className="recent-nav-btn"
              onClick={() => stepRecent(-1)}
              disabled={recentItems.length <= 1}
              aria-label="이전 소식"
            >
              <ChevronLeft size={14} />
            </button>
            <button
              type="button"
              className="recent-nav-btn"
              onClick={() => stepRecent(1)}
              disabled={recentItems.length <= 1}
              aria-label="다음 소식"
            >
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function HoldingsPane({
  stocks,
  onOpen,
  onReorder,
  onRemove,
}: {
  stocks: ResearchStock[];
  onOpen: (stock: ResearchStock) => void;
  onReorder: (fromIndex: number, toIndex: number) => void;
  onRemove: (stock: ResearchStock) => void;
}) {
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [overIndex, setOverIndex] = useState<number | null>(null);
  const totalMarketValue = stocks.reduce((sum, stock) => sum + stock.marketValue, 0);
  const totalCost = stocks.reduce((sum, stock) => {
    if (!stock.quantity || !stock.averageCost) return sum + stock.marketValue;
    return sum + stock.quantity * stock.averageCost;
  }, 0);
  const totalProfit = totalMarketValue - totalCost;
  const totalProfitPct = totalCost > 0 ? (totalProfit / totalCost) * 100 : 0;

  function endDrag() {
    setDragIndex(null);
    setOverIndex(null);
  }

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
        {stocks.map((stock, index) => (
          <StockCard
            key={`${stock.market}:${stock.code}`}
            stock={stock}
            index={index}
            dragging={dragIndex === index}
            dropTarget={
              overIndex === index && dragIndex !== null && dragIndex !== index
            }
            onOpen={() => onOpen(stock)}
            onRemove={() => onRemove(stock)}
            onDragStart={() => setDragIndex(index)}
            onDragEnterCard={() => setOverIndex(index)}
            onDropCard={() => {
              if (dragIndex !== null) onReorder(dragIndex, index);
              endDrag();
            }}
            onDragEnd={endDrag}
          />
        ))}
      </div>
    </section>
  );
}

function StockCard({
  stock,
  index,
  dragging,
  dropTarget,
  onOpen,
  onRemove,
  onDragStart,
  onDragEnterCard,
  onDropCard,
  onDragEnd,
}: {
  stock: ResearchStock;
  index: number;
  dragging: boolean;
  dropTarget: boolean;
  onOpen: () => void;
  onRemove: () => void;
  onDragStart: () => void;
  onDragEnterCard: () => void;
  onDropCard: () => void;
  onDragEnd: () => void;
}) {
  const cardRef = useRef<HTMLDivElement>(null);
  const [confirming, setConfirming] = useState(false);
  const up = stock.changePct >= 0;
  const hasChange = stock.spark.length > 1;
  const hasValuation =
    stock.quantity !== null && stock.averageCost !== null && stock.spark.length > 0;
  return (
    <div
      ref={cardRef}
      role="button"
      tabIndex={0}
      className="stock-card"
      data-dragging={dragging ? "true" : undefined}
      data-drop-target={dropTarget ? "true" : undefined}
      onClick={onOpen}
      onMouseLeave={() => setConfirming(false)}
      onKeyDown={(event) => {
        if (event.target !== event.currentTarget) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen();
        }
      }}
      onDragEnter={(event) => {
        event.preventDefault();
        onDragEnterCard();
      }}
      onDragOver={(event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
      }}
      onDrop={(event) => {
        event.preventDefault();
        onDropCard();
      }}
    >
      <div className="row">
        <span
          className="drag-handle"
          draggable
          onClick={(event) => event.stopPropagation()}
          onDragStart={(event) => {
            event.dataTransfer.effectAllowed = "move";
            event.dataTransfer.setData("text/plain", String(index));
            if (cardRef.current) {
              event.dataTransfer.setDragImage(cardRef.current, 24, 20);
            }
            onDragStart();
          }}
          onDragEnd={onDragEnd}
          aria-label={`${stock.name} 카드 순서 이동`}
          title="드래그해서 카드 순서를 바꿀 수 있어요"
        >
          <GripVertical size={14} />
        </span>
        <span className="name">{stock.name}</span>
        <span className="spacer" />
        <a
          className="stock-card-report-link"
          href={naverResearchUrl(stock)}
          target="_blank"
          rel="noreferrer"
          title={`${stock.name} 네이버 리포트`}
          aria-label={`${stock.name} 네이버 리포트 새 탭으로 열기`}
          onClick={(event) => event.stopPropagation()}
          onDragStart={(event) => event.preventDefault()}
        >
          <FileText size={14} />
        </a>
        <MktChip market={stock.market} />
      </div>
      <button
        type="button"
        className={`card-remove${confirming ? " card-remove--armed" : ""}`}
        aria-label={confirming ? `${stock.name} 제거 확인` : `${stock.name} 카드 제거`}
        title={confirming ? "한 번 더 누르면 제거돼요" : "카드 제거"}
        onClick={(event) => {
          event.stopPropagation();
          if (confirming) onRemove();
          else setConfirming(true);
        }}
      >
        {confirming ? "삭제" : <X size={11} />}
      </button>
      <div className="row stock-price-row">
        <span className="price">{formatMoney(stock.price)}</span>
        {hasChange ? (
          <span className={`chg ${up ? "chg--pos" : "chg--neg"}`}>
            {up ? "▲" : "▼"} {Math.abs(stock.changePct).toFixed(2)}%
          </span>
        ) : (
          <span className="chg chg--muted">-</span>
        )}
      </div>
      <Sparkline data={stock.spark} />
      <div className="foot">
        <span className="pos-info">
          {stock.quantity ?? "-"}주 · 평단 {stock.averageCost ? stock.averageCost.toLocaleString() : "-"}
        </span>
        {hasValuation ? (
          <span className={`pl ${stock.profitLoss >= 0 ? "pl--pos" : "pl--neg"}`}>
            {formatSignedMoney(stock.profitLoss)} ({formatPct(stock.profitLossPct)})
          </span>
        ) : (
          <span className="pl pl--muted">-</span>
        )}
      </div>
    </div>
  );
}

function Orbital({
  stocks,
  countdown,
  refreshing,
  manualCooldown,
  onRefresh,
  onPlanetClick,
}: {
  stocks: ResearchStock[];
  countdown: string;
  refreshing: boolean;
  manualCooldown: string | null;
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
        <button
          className="refresh-btn"
          onClick={onRefresh}
          disabled={manualCooldown !== null}
          data-loading={refreshing ? "true" : "false"}
          title={
            manualCooldown
              ? `${manualCooldown} 후 다시 새로고침할 수 있습니다`
              : "지금 새로고침"
          }
        >
          <RefreshCw size={12} />
          {manualCooldown ?? "지금"}
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
  const size = stock.unreadCount > 0 ? Math.min(82, 28 + stock.unreadCount * 10.5) : 28;
  const hasUnread = stock.unreadCount > 0;
  const fontSize = Math.max(11, Math.min(22, size * 0.42));
  return (
    <button
      className="planet"
      data-hover={hovered ? "true" : "false"}
      data-has-news={hasUnread ? "true" : "false"}
      onMouseEnter={() => onHover(stock.code)}
      onMouseLeave={() => onHover(null)}
      onFocus={() => onHover(stock.code)}
      onBlur={() => onHover(null)}
      onClick={() => onClick(stock)}
      aria-label={`${stock.name}: 미확인 뉴스 ${stock.unreadNewsCount}, 공시 ${stock.unreadDisclosureCount}`}
    >
      <span
        className="planet-disc"
        data-has-news={hasUnread ? "true" : "false"}
        style={{ width: size, height: size, fontSize }}
      >
        {hasUnread ? stock.unreadCount : ""}
        {hasUnread && <span className="planet-blip" />}
      </span>
      <span className="planet-label">{stock.name}</span>
      {hovered && (
        <span className="planet-tooltip" role="tooltip">
          <span>
            <span className="ttkey">뉴스</span> <b>{stock.unreadNewsCount}</b>
          </span>
          <span>
            <span className="ttkey">공시</span> <b>{stock.unreadDisclosureCount}</b>
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
  readIds,
  markRead,
  bookmarkIds,
  toggleBookmark,
  notes,
  saveIssueNote,
  onRequestAiSummary,
}: {
  stocks: ResearchStock[];
  issues: ResearchIssue[];
  filter: FeedFilter;
  setFilter: (filter: FeedFilter) => void;
  selectedIssueId: string | null;
  setSelectedIssueId: (id: string | null) => void;
  readIds: Set<string>;
  markRead: (id: string) => void;
  bookmarkIds: Set<string>;
  toggleBookmark: (id: string) => void;
  notes: Record<string, string>;
  saveIssueNote: (id: string, text: string) => void;
  onRequestAiSummary: (newsItemId: number) => Promise<void>;
}) {
  const [query, setQuery] = useState("");
  const emptyMessage =
    stocks.length === 0
      ? "등록한 종목이 아직 없어요"
      : filter.bookmarkedOnly
        ? "북마크한 항목이 없어요"
        : "조건에 맞는 항목이 없어요";
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = issues.filter((issue) => {
      if (filter.stockCodes?.length && !filter.stockCodes.includes(issue.stockCode))
        return false;
      if (filter.type && issue.type !== filter.type) return false;
      if (filter.sentiment && issue.sentiment !== filter.sentiment) return false;
      if (filter.minImportance && issue.importance < filter.minImportance) return false;
      if (filter.bookmarkedOnly && !bookmarkIds.has(issue.id)) return false;
      if (
        q &&
        !`${issue.stockName} ${issue.stockCode} ${issue.title}`
          .toLowerCase()
          .includes(q)
      ) {
        return false;
      }
      return true;
    });
    // A preferred stock shares its common stock's issues, so the same item can
    // surface under both — collapse duplicates so the feed lists each once.
    const seen = new Set<string>();
    return filtered.filter((issue) => {
      if (seen.has(issue.id)) return false;
      seen.add(issue.id);
      return true;
    });
  }, [issues, filter, query, bookmarkIds]);
  const selected = visible.find((issue) => issue.id === selectedIssueId) ?? visible[0] ?? null;
  const selectedIndex = selected ? visible.findIndex((issue) => issue.id === selected.id) : -1;
  const prevIssue = selectedIndex > 0 ? visible[selectedIndex - 1] : null;
  const nextIssue =
    selectedIndex >= 0 && selectedIndex < visible.length - 1 ? visible[selectedIndex + 1] : null;

  useEffect(() => {
    if (selected && selected.id !== selectedIssueId) {
      setSelectedIssueId(selected.id);
    }
  }, [selected, selectedIssueId, setSelectedIssueId]);

  // Viewing an issue's detail marks it read (clears the unread indicator).
  useEffect(() => {
    if (selected) markRead(selected.id);
  }, [selected, markRead]);

  return (
    <div className="col feed-view">
      <FeedFilters
        stocks={stocks}
        filter={filter}
        setFilter={setFilter}
        query={query}
        setQuery={setQuery}
      />
      <div className="feed">
        <div className="feed-list">
          {visible.length === 0 && (
            <div className="feed-pane-empty">
              <span>{emptyMessage}</span>
              {stocks.length > 0 && (
                <Button size="sm" variant="ghost" onClick={() => setFilter({})}>
                  필터 초기화
                </Button>
              )}
            </div>
          )}
          {visible.map((issue) => (
            <FeedListItem
              key={issue.id}
              issue={issue}
              selected={selected?.id === issue.id}
              unread={!readIds.has(issue.id)}
              bookmarked={bookmarkIds.has(issue.id)}
              onClick={() => setSelectedIssueId(issue.id)}
            />
          ))}
        </div>
        <FeedReadingPane
          issue={selected}
          bookmarked={selected !== null && bookmarkIds.has(selected.id)}
          onToggleBookmark={() => {
            if (selected) toggleBookmark(selected.id);
          }}
          note={selected ? notes[selected.id] ?? "" : ""}
          onSaveNote={(text) => {
            if (selected) saveIssueNote(selected.id, text);
          }}
          onPrev={prevIssue ? () => setSelectedIssueId(prevIssue.id) : undefined}
          onNext={nextIssue ? () => setSelectedIssueId(nextIssue.id) : undefined}
          onRequestAiSummary={onRequestAiSummary}
        />
      </div>
    </div>
  );
}

function StockFilterDropdown({
  stocks,
  selected,
  onChange,
}: {
  stocks: ResearchStock[];
  selected: string[];
  onChange: (codes: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const wrapRef = useRef<HTMLDivElement>(null);

  // Close the popup on an outside click or the Escape key.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  // An empty selection is the "전체" mode: every stock passes the filter.
  const isAll = selected.length === 0;

  const visibleStocks = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return stocks;
    return stocks.filter(
      (stock) =>
        stock.name.toLowerCase().includes(term) || stock.code.includes(term),
    );
  }, [stocks, search]);

  // Checking every stock one by one collapses back to "전체" mode, since the
  // two states filter to exactly the same issues.
  function toggleStock(code: string) {
    const next = selected.includes(code)
      ? selected.filter((item) => item !== code)
      : [...selected, code];
    onChange(next.length === stocks.length ? [] : next);
  }

  // "전체" stays "전체"; a partial selection clears all the way back to "전체".
  function toggleAll() {
    if (!isAll) onChange([]);
  }

  let triggerLabel: ReactNode;
  if (isAll) {
    triggerLabel = <span className="muted">종목 선택</span>;
  } else if (selected.length === 1) {
    triggerLabel =
      stocks.find((stock) => stock.code === selected[0])?.name ?? selected[0];
  } else {
    triggerLabel = (
      <>
        선택한 종목{" "}
        <span className="combo-trigger-count">{selected.length}</span>
      </>
    );
  }

  return (
    <div className="combo" ref={wrapRef}>
      <button
        type="button"
        className="combo-trigger"
        data-state={isAll ? "all" : "some"}
        data-open={open ? "true" : "false"}
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        {triggerLabel}
        <ChevronDown className="chev" size={14} />
      </button>
      {open && (
        <div className="combo-pop" role="listbox" aria-label="종목 필터">
          <div className="combo-pop-head">
            <div className="combo-search-wrap">
              <Search size={14} />
              <input
                className="combo-search"
                placeholder="종목 검색"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                autoFocus
              />
            </div>
          </div>
          <div className="combo-list">
            {!search && (
              <div
                className="combo-item combo-item--all"
                data-checked={isAll ? "true" : "false"}
                data-indeterminate={isAll ? "false" : "true"}
                onClick={toggleAll}
                role="option"
                aria-selected={isAll}
              >
                <span className="combo-check" aria-hidden="true" />
                <span className="combo-name">전체</span>
                <span className="combo-summary">{stocks.length}개 종목</span>
              </div>
            )}
            {visibleStocks.map((stock) => {
              const checked = selected.includes(stock.code);
              return (
                <div
                  key={stock.id}
                  className="combo-item"
                  data-checked={checked ? "true" : "false"}
                  onClick={() => toggleStock(stock.code)}
                  role="option"
                  aria-selected={checked}
                >
                  <span className="combo-check" aria-hidden="true" />
                  <MktChip market={stock.market} />
                  <span className="combo-name">{stock.name}</span>
                  {stock.unreadCount > 0 && (
                    <span className="combo-new-count">+{stock.unreadCount}</span>
                  )}
                </div>
              );
            })}
            {search && visibleStocks.length === 0 && (
              <div className="combo-empty">검색 결과가 없어요</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function FeedFilters({
  stocks,
  filter,
  setFilter,
  query,
  setQuery,
}: {
  stocks: ResearchStock[];
  filter: FeedFilter;
  setFilter: (filter: FeedFilter) => void;
  query: string;
  setQuery: (value: string) => void;
}) {
  const types: Array<{ value: IssueType | "all"; label: string }> = [
    { value: "all", label: "전체" },
    { value: "news", label: "뉴스" },
    { value: "disc", label: "공시" },
  ];
  const sentiments: Array<{ value: SentKey | "all"; label: string }> = [
    { value: "all", label: "감성 전체" },
    { value: "pos", label: "긍정" },
    { value: "neu", label: "중립" },
    { value: "neg", label: "부정" },
  ];
  return (
    <div className="feed-filters">
      <div className="feed-search">
        <Search size={15} />
        <input
          placeholder="종목명·코드·제목 검색"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          aria-label="피드 검색"
        />
        {query && (
          <button
            type="button"
            className="feed-search-clear"
            onClick={() => setQuery("")}
            aria-label="검색어 지우기"
          >
            <X size={13} />
          </button>
        )}
      </div>
      <span className="filter-label">종목</span>
      <div className="filter-group">
        <Chip
          active={!filter.stockCodes?.length}
          onClick={() => setFilter({ ...filter, stockCodes: null })}
        >
          전체
        </Chip>
        {stocks.length > 0 && (
          <StockFilterDropdown
            stocks={stocks}
            selected={filter.stockCodes ?? []}
            onChange={(codes) =>
              setFilter({ ...filter, stockCodes: codes.length === 0 ? null : codes })
            }
          />
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
        중요
      </Chip>
      <Chip
        ghost
        active={Boolean(filter.bookmarkedOnly)}
        onClick={() => setFilter({ ...filter, bookmarkedOnly: !filter.bookmarkedOnly })}
      >
        <Bookmark size={12} />
        북마크
      </Chip>
    </div>
  );
}

function FeedListItem({
  issue,
  selected,
  unread,
  bookmarked,
  onClick,
}: {
  issue: ResearchIssue;
  selected: boolean;
  unread: boolean;
  bookmarked: boolean;
  onClick: () => void;
}) {
  return (
    <button className="feed-item" aria-current={selected ? "true" : "false"} onClick={onClick}>
      <span className={`s-rail s-rail--${issue.sentiment}`} />
      <span className="body">
        <span className="meta">
          <MktChip market={issue.market} />
          <span className="feed-stock-name">{issue.stockName}</span>
          <span
            className="feed-unread-dot"
            data-unread={unread ? "true" : "false"}
            aria-hidden="true"
          />
          {bookmarked && (
            <span className="feed-bookmark-flag" role="img" aria-label="북마크함">
              <Bookmark size={12} fill="currentColor" />
            </span>
          )}
        </span>
        <span className="title">{issue.title}</span>
        <span className="badges">
          <TypeBadge type={issue.type} />
          {issue.clusterSize > 1 && <span className="cluster-badge">관련 {issue.clusterSize}건</span>}
          <ImportanceDots value={issue.importance} />
        </span>
      </span>
      <span className="feed-item-time">{formatTime(issue.occurredAt)}</span>
    </button>
  );
}

function clusteredSourceLabel(issue: ResearchIssue): string {
  if (issue.clusterSize <= 1) return issue.source;
  if (issue.clusterSources.length <= 1) return `${issue.source} · ${issue.clusterSize}건`;
  return `${issue.clusterSources[0]} 외 ${issue.clusterSources.length - 1}곳`;
}

// Collapsed "묶인 뉴스" view: keep the first RELATED_COLLAPSE_LIMIT articles,
// but always include the active one so the current selection stays visible.
function collapsedRelatedArticles(articles: RelatedArticle[], active: RelatedArticle): RelatedArticle[] {
  const head = articles.slice(0, RELATED_COLLAPSE_LIMIT);
  return head.some((article) => article.id === active.id) ? head : [...head, active];
}

function FeedReadingPane({
  issue,
  bookmarked,
  onToggleBookmark,
  note,
  onSaveNote,
  onPrev,
  onNext,
  onRequestAiSummary,
}: {
  issue: ResearchIssue | null;
  bookmarked: boolean;
  onToggleBookmark: () => void;
  note: string;
  onSaveNote: (text: string) => void;
  onPrev?: () => void;
  onNext?: () => void;
  onRequestAiSummary: (newsItemId: number) => Promise<void>;
}) {
  const [activeArticleId, setActiveArticleId] = useState<string | null>(null);
  const [relatedExpanded, setRelatedExpanded] = useState(false);
  // Items currently being summarized — keeps the spinner pinned.
  const [pendingAiIds, setPendingAiIds] = useState<Set<number>>(new Set());
  // Items we already asked the server about for this issue. Held in a ref
  // (not state) so the trigger effect's deps stay stable: a response that
  // comes back without an AI summary (no key, LLM failure) must NOT cause the
  // effect to fire again on the same article — otherwise pending toggles in
  // a loop and the section flickers between "생성 중…" and "원문 요약".
  const attemptedAiIdsRef = useRef<Set<number>>(new Set());

  useEffect(() => {
    setActiveArticleId(null);
    setRelatedExpanded(false);
    setPendingAiIds(new Set());
    attemptedAiIdsRef.current = new Set();
  }, [issue?.id]);

  if (!issue) {
    return (
      <div className="feed-pane">
        <div className="feed-pane-empty">
          <FileText size={36} />
          <div>왼쪽 목록에서 항목을 선택해 주세요</div>
        </div>
      </div>
    );
  }

  const sourceLabel = clusteredSourceLabel(issue);
  const representativeArticle =
    issue.relatedArticles.find((article) => article.isRepresentative) ??
    issue.relatedArticles.find((article) => article.itemId === issue.itemId) ??
    relatedArticleFromIssue(issue, true);
  const activeArticle =
    issue.clusterSize > 1
      ? issue.relatedArticles.find((article) => article.id === activeArticleId) ?? representativeArticle
      : representativeArticle;
  const articleRoleLabel = activeArticle.isRepresentative ? "대표" : "관련";

  const relatedCollapsible = issue.relatedArticles.length > RELATED_COLLAPSE_LIMIT;
  const visibleArticles =
    relatedCollapsible && !relatedExpanded
      ? collapsedRelatedArticles(issue.relatedArticles, activeArticle)
      : issue.relatedArticles;
  const relatedHiddenCount = issue.relatedArticles.length - visibleArticles.length;

  // Trigger an on-demand AI summary the first time a news article is opened
  // without one — the server-side eager pass only covers the latest few per
  // symbol, so anything older or a bundled "관련" article lands here. Only
  // news rows are summarized; disclosures still rely on the rule-based path.
  const activeNewsItemId = issue.type === "news" ? activeArticle.itemId : null;
  const activeAiSummary = activeArticle.aiSummary;
  const isAiPending = activeNewsItemId !== null && pendingAiIds.has(activeNewsItemId);
  useEffect(() => {
    if (activeNewsItemId === null) return;
    if (activeAiSummary) return;
    if (attemptedAiIdsRef.current.has(activeNewsItemId)) return;
    const newsItemId = activeNewsItemId;
    attemptedAiIdsRef.current.add(newsItemId);
    setPendingAiIds((prev) => {
      const next = new Set(prev);
      next.add(newsItemId);
      return next;
    });
    // Always clear the pending mark when the request settles. On success the
    // updated row arrives via setDetails and the section flips to the new
    // summary; on failure (or when no key is configured) the section settles
    // on the rule-based fallback label and stays there.
    onRequestAiSummary(newsItemId).finally(() => {
      setPendingAiIds((prev) => {
        if (!prev.has(newsItemId)) return prev;
        const next = new Set(prev);
        next.delete(newsItemId);
        return next;
      });
    });
  }, [activeNewsItemId, activeAiSummary, onRequestAiSummary]);

  const aiSummaryText = activeAiSummary ?? activeArticle.summary;
  const aiSummaryStatus: "ready" | "loading" | "fallback" = activeAiSummary
    ? "ready"
    : isAiPending
      ? "loading"
      : "fallback";

  return (
    <div className="feed-pane">
      <article className="feed-article">
        <div className="meta-line">
          <TypeBadge type={issue.type} />
          <MktChip market={issue.market} />
          <span>
            <b>{issue.stockName}</b> · {issue.stockCode}
          </span>
          <span>·</span>
          <span>{issue.clusterSize > 1 ? `${activeArticle.source} · ${articleRoleLabel}` : sourceLabel}</span>
          <span>·</span>
          <span className="mono">{formatTime(activeArticle.occurredAt)}</span>
          <span className="spacer" />
          <button
            type="button"
            className="icon-btn"
            data-bookmarked={bookmarked ? "true" : "false"}
            title={bookmarked ? "북마크 해제" : "북마크"}
            aria-pressed={bookmarked}
            onClick={onToggleBookmark}
          >
            <Bookmark size={16} fill={bookmarked ? "currentColor" : "none"} />
          </button>
          <a className="icon-btn" href={activeArticle.url} target="_blank" rel="noreferrer" title="원문 새 탭">
            <ArrowUpRight size={16} />
          </a>
        </div>
        <h1>{activeArticle.title}</h1>
        <div className="pills">
          <span>
            <span className="pill-label">감성 </span>
            <SentPill sentiment={activeArticle.sentiment} />
          </span>
          <span>
            <span className="pill-label">중요도 </span>
            <span className="pill-value">
              <ImportanceDots value={activeArticle.importance} /> {activeArticle.importance}/5
            </span>
          </span>
          <span>
            <span className="pill-label">포트폴리오 영향 </span>
            <span className="pill-value">{activeArticle.importance >= 4 ? "높음" : activeArticle.importance >= 3 ? "중간" : "낮음"}</span>
          </span>
          {issue.clusterSize > 1 && (
            <span>
              <span className="pill-label">관련 기사 </span>
              <span className="pill-value">
                {issue.clusterSize}건 · {issue.clusterSources.length}곳
              </span>
            </span>
          )}
          <span className="muted analysis-meta">분석 {activeArticle.modelVersion} · {formatTime(activeArticle.collectedAt)}</span>
        </div>
        <section>
          <h2>
            <Sparkles size={11} /> AI 요약
            {aiSummaryStatus === "loading" && (
              <span className="muted"> · 생성 중…</span>
            )}
            {aiSummaryStatus === "fallback" && (
              <span className="muted"> · 원문 요약</span>
            )}
          </h2>
          <p className="summary">{aiSummaryText}</p>
        </section>
        <section>
          <h2>포트폴리오 영향 분석</h2>
          <p className="analysis">{activeArticle.impact}</p>
        </section>
        {issue.clusterSize > 1 && (
          <section>
            <h2>묶인 뉴스</h2>
            <div className="related-list">
              {visibleArticles.map((article) => (
                <div
                  key={`${article.id}-${article.url}`}
                  className="related-link"
                  aria-current={activeArticle.id === article.id ? "true" : "false"}
                >
                  <button
                    type="button"
                    className="related-select"
                    onClick={() => setActiveArticleId(article.id)}
                  >
                    <span className="related-title-wrap">
                      <span className="related-title">{article.title}</span>
                      {article.isRepresentative && <span className="related-rep">대표</span>}
                    </span>
                    <span className="related-meta">
                      {article.source} · {formatTime(article.occurredAt)}
                    </span>
                  </button>
                  <a
                    className="related-open"
                    href={article.url}
                    target="_blank"
                    rel="noreferrer"
                    title="원문 새 탭"
                  >
                    <ArrowUpRight size={14} />
                  </a>
                </div>
              ))}
              {(relatedExpanded || relatedHiddenCount > 0) && (
                <button
                  type="button"
                  className="related-toggle"
                  data-open={relatedExpanded ? "true" : "false"}
                  aria-expanded={relatedExpanded}
                  onClick={() => setRelatedExpanded((value) => !value)}
                >
                  {relatedExpanded ? "접기" : `펼치기 (+${relatedHiddenCount})`}
                  <ChevronDown className="chev" size={14} />
                </button>
              )}
            </div>
          </section>
        )}
        <section>
          <h2>분석 근거</h2>
          <div className="keywords">
            {activeArticle.keywords.map((keyword) => (
              <span key={keyword} className="keyword">
                {keyword}
              </span>
            ))}
          </div>
          <a className="original-card" href={activeArticle.url} target="_blank" rel="noreferrer">
            <span>
              <Paperclip size={14} /> 원문 · {activeArticle.source}
            </span>
            <span className="open-link">
              새 탭으로 열기 <ArrowUpRight size={12} />
            </span>
          </a>
        </section>
        <FeedNoteSection key={issue.id} note={note} onSave={onSaveNote} />
        <div className="actions">
          <Button icon={<ChevronLeft size={14} />} disabled={!onPrev} onClick={onPrev}>
            이전
          </Button>
          <span className="spacer" />
          <Button
            variant="primary"
            icon={<ArrowRight size={14} />}
            disabled={!onNext}
            onClick={onNext}
          >
            다음
          </Button>
        </div>
      </article>
    </div>
  );
}

function FeedNoteSection({
  note,
  onSave,
}: {
  note: string;
  onSave: (text: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  function startEditing() {
    setDraft(note);
    setEditing(true);
  }

  function save() {
    onSave(draft.trim());
    setEditing(false);
  }

  return (
    <section className="feed-note">
      <h2>
        <StickyNote size={11} /> 메모
      </h2>
      {editing ? (
        <div className="note-editor">
          <textarea
            className="note-input"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="이 이슈에 대한 메모를 남겨보세요"
            rows={4}
            autoFocus
          />
          <div className="note-actions">
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
              취소
            </Button>
            <Button size="sm" variant="primary" onClick={save}>
              저장
            </Button>
          </div>
        </div>
      ) : note ? (
        <div className="note-saved">
          <p className="note-text">{note}</p>
          <div className="note-actions">
            <Button size="sm" variant="ghost" onClick={() => onSave("")}>
              삭제
            </Button>
            <Button size="sm" onClick={startEditing}>
              편집
            </Button>
          </div>
        </div>
      ) : (
        <button type="button" className="note-add" onClick={startEditing}>
          <Plus size={14} /> 메모 추가
        </button>
      )}
    </section>
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
  const variant = market.toUpperCase() === "KOSDAQ" ? "kosdaq" : "kospi";
  return <span className={`chip chip--mkt chip--mkt--${variant}`}>{market}</span>;
}

/**
 * Reserved ad-slot position (MVP-12). Renders an inert container so the layout
 * has a defined place for ads; a later ticket wires an ad network in.
 */
function AdSlot({ slot }: { slot: string }) {
  return <div className="ad-slot" data-ad-slot={slot} aria-hidden="true" />;
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

function formatTradeDate(value: string): string {
  const parts = value.split("-");
  if (parts.length !== 3) return value;
  return `${Number(parts[1])}월 ${Number(parts[2])}일`;
}

/**
 * Daily-close sparkline. Hovering reads out the close price and trading day
 * at the nearest point; the line color reflects the period's net direction.
 */
function Sparkline({ data }: { data: DailyPrice[] }) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const width = 260;
  const height = 40;

  if (data.length < 2) {
    return <span className="spark spark--empty">일별 시세 준비 중</span>;
  }

  const closes = data.map((point) => point.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;
  const positive = closes[closes.length - 1] >= closes[0];
  const xOf = (index: number) => (index / (data.length - 1)) * width;
  const yOf = (value: number) => height - 4 - ((value - min) / range) * (height - 8);
  const points = data
    .map((point, index) => `${xOf(index)},${yOf(point.close)}`)
    .join(" ");
  const fillPoints = `0,${height} ${points} ${width},${height}`;

  function handleMove(event: React.MouseEvent<HTMLSpanElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width === 0) return;
    const ratio = (event.clientX - rect.left) / rect.width;
    const index = Math.round(ratio * (data.length - 1));
    setHoverIndex(Math.min(data.length - 1, Math.max(0, index)));
  }

  const active = hoverIndex === null ? null : data[hoverIndex];
  const activeLeft = hoverIndex === null ? 0 : (hoverIndex / (data.length - 1)) * 100;
  const activeTop = active ? (yOf(active.close) / height) * 100 : 0;

  return (
    <span
      className={`spark ${positive ? "spark--pos" : "spark--neg"}`}
      onMouseMove={handleMove}
      onMouseLeave={() => setHoverIndex(null)}
    >
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true">
        <polygon points={fillPoints} />
        <polyline points={points} />
      </svg>
      {active && (
        <>
          <span className="spark-cursor" style={{ left: `${activeLeft}%` }} />
          <span
            className="spark-dot"
            style={{ left: `${activeLeft}%`, top: `${activeTop}%` }}
          />
          <span
            className="spark-tip"
            style={{ left: `${Math.min(85, Math.max(15, activeLeft))}%` }}
          >
            <b>{formatMoney(active.close)}</b>
            <span>{formatTradeDate(active.trade_date)}</span>
          </span>
        </>
      )}
    </span>
  );
}

export default App;
