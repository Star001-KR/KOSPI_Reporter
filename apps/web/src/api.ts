import type {
  AuthUser,
  DailyPrice,
  DailyReportList,
  NewsItem,
  PortfolioBrief,
  SymbolDetail,
  SymbolLookupResult,
  SymbolRecord,
} from "./types";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

/** An error carrying the HTTP status so callers can branch on it (e.g. 409). */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    let message = `Request failed with ${response.status}`;
    try {
      const body = await response.json();
      message = body.detail ?? message;
    } catch {
      // Keep the status-based message.
    }
    throw new ApiError(response.status, message);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

export interface SymbolPayload {
  market: string;
  code: string;
  name: string;
  memo: string | null;
  holding: {
    quantity: number | null;
    average_cost: number | null;
    market_value: number | null;
    portfolio_weight: number | null;
  } | null;
}

export const api = {
  googleLoginUrl: () => `${API_BASE_URL}/api/auth/google/start`,
  getMe: () => request<AuthUser>("/api/me"),
  logout: () =>
    request<void>("/api/auth/logout", {
      method: "POST",
    }),
  getBrief: () => request<PortfolioBrief>("/api/portfolio/brief"),
  listSymbols: () => request<SymbolRecord[]>("/api/symbols"),
  lookupSymbols: (q: string, market: string) =>
    request<SymbolLookupResult[]>(
      `/api/symbols/lookup?q=${encodeURIComponent(q)}&market=${encodeURIComponent(market)}`,
    ),
  getSymbol: (id: number) => request<SymbolDetail>(`/api/symbols/${id}`),
  getSymbolPrices: (id: number) =>
    request<DailyPrice[]>(`/api/symbols/${id}/prices`),
  createSymbol: (payload: SymbolPayload) =>
    request<SymbolRecord>("/api/symbols", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateSymbol: (id: number, payload: Partial<SymbolPayload>) =>
    request<SymbolRecord>(`/api/symbols/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteSymbol: (id: number) =>
    request<void>(`/api/symbols/${id}`, {
      method: "DELETE",
    }),
  // Lazy on-demand AI summary for a news item that was not summarized
  // eagerly at collection time. The server caches the result, so calling
  // again just returns whatever is already stored.
  generateNewsAiSummary: (newsId: number) =>
    request<NewsItem>(`/api/news/${newsId}/ai-summary`, {
      method: "POST",
    }),
  // Every symbol's daily report for the latest published date (or empty when
  // the morning batch has not run yet). Read-only, like the other GETs.
  getDailyReports: () => request<DailyReportList>("/api/daily-reports"),
};
