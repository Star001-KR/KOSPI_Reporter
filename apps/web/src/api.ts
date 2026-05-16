import type {
  CollectionRun,
  DailyPrice,
  PortfolioBrief,
  SymbolDetail,
  SymbolLookupResult,
  SymbolRecord,
} from "./types";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
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
    throw new Error(message);
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
  runCollection: () =>
    request<CollectionRun>("/api/collections/run", {
      method: "POST",
      body: JSON.stringify({}),
    }),
  listRuns: () => request<CollectionRun[]>("/api/collections/runs"),
  seedDemo: () =>
    request<{ symbol_id: number; news_inserted: number; disclosures_inserted: number }[]>(
      "/api/dev/seed",
      { method: "POST" },
    ),
  createMockActivity: (id: number) =>
    request<{ symbol_id: number; news_inserted: number; disclosures_inserted: number }>(
      `/api/symbols/${id}/mock-activity`,
      { method: "POST" },
    ),
};
