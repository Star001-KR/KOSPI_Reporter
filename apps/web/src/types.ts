export type Sentiment = "positive" | "negative" | "neutral";

export interface HoldingInput {
  quantity: number | null;
  average_cost: number | null;
  market_value: number | null;
  portfolio_weight: number | null;
}

export interface Holding extends HoldingInput {
  id: number;
  symbol_id: number;
  created_at: string;
  updated_at: string;
}

export interface SymbolRecord {
  id: number;
  market: string;
  code: string;
  name: string;
  memo: string | null;
  created_at: string;
  updated_at: string;
  holding: Holding | null;
}

export interface SymbolLookupResult {
  market: string;
  code: string;
  name: string;
}

export interface AuthUser {
  id: number;
  email: string | null;
  display_name: string | null;
  avatar_url: string | null;
  created_at: string;
  last_login_at: string | null;
}

export interface AnalysisResult {
  id: number;
  target_type: "news" | "disclosure";
  target_id: number;
  summary: string;
  sentiment: Sentiment;
  importance: number;
  portfolio_impact: string;
  rationale: string | null;
  model_name: string;
  model_version: string;
  created_at: string;
}

export interface NewsItem {
  id: number;
  symbol_id: number;
  title: string;
  summary: string | null;
  source: string | null;
  original_url: string;
  canonical_url: string;
  published_at: string | null;
  collected_at: string;
  ai_summary: string | null;
  ai_summary_model: string | null;
  ai_summary_at: string | null;
}

export interface Disclosure {
  id: number;
  symbol_id: number;
  rcept_no: string;
  report_name: string;
  corp_code: string | null;
  corp_name: string | null;
  submitted_at: string | null;
  original_url: string;
  collected_at: string;
}

export interface AnalyzedNewsItem {
  item: NewsItem;
  analysis: AnalysisResult | null;
}

export interface AnalyzedDisclosure {
  item: Disclosure;
  analysis: AnalysisResult | null;
}

export interface SymbolDetail extends SymbolRecord {
  news_items: AnalyzedNewsItem[];
  disclosures: AnalyzedDisclosure[];
}

export interface BriefPosition {
  symbol: SymbolRecord;
  news_count: number;
  disclosure_count: number;
  latest_collected_at: string | null;
}

export interface BriefItem {
  kind: "news" | "disclosure";
  symbol_id: number;
  symbol_name: string;
  title: string;
  source: string | null;
  original_url: string;
  occurred_at: string | null;
  sentiment: Sentiment | null;
  importance: number | null;
}

export interface PortfolioBrief {
  total_symbols: number;
  total_market_value: number;
  latest_collected_at: string | null;
  positions: BriefPosition[];
  latest_items: BriefItem[];
}

/**
 * A symbol the visitor is tracking. Stored only in the browser (localStorage),
 * never on the server, so each visitor's watchlist and holdings stay private.
 */
export interface WatchlistEntry {
  market: string;
  code: string;
  name: string;
  quantity: number | null;
  averageCost: number | null;
  memo: string | null;
}

/** A single trading day's close price for a symbol. */
export interface DailyPrice {
  trade_date: string;
  close: number;
}

export type Recommendation = "buy" | "hold" | "sell";

/** A symbol's morning daily report with a buy/hold/sell opinion. */
export interface DailyReportItem {
  id: number;
  symbol_id: number;
  report_date: string;
  recommendation: Recommendation;
  summary: string;
  rationale: string | null;
  prev_trade_date: string | null;
  prev_close: number | null;
  change_pct: number | null;
  model_name: string;
  created_at: string;
  symbol_name: string;
  symbol_code: string;
  symbol_market: string;
}

export interface DailyReportList {
  report_date: string | null;
  items: DailyReportItem[];
}
