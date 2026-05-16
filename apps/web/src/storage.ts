/**
 * Browser-local watchlist storage (MVP-09).
 *
 * A visitor's watchlist and holdings (quantity / average cost / memo) live only
 * in this browser via localStorage. The server stores public research data
 * (news, disclosures, analysis) but never a visitor's personal portfolio.
 */

import type { WatchlistEntry } from "./types";

const WATCHLIST_KEY = "kospi.watchlist.v1";

function isEntry(value: unknown): value is WatchlistEntry {
  if (!value || typeof value !== "object") return false;
  const entry = value as Record<string, unknown>;
  return (
    typeof entry.market === "string" &&
    typeof entry.code === "string" &&
    typeof entry.name === "string"
  );
}

/** Stable key for a symbol identity, used to dedupe watchlist entries. */
export function watchlistKey(entry: { market: string; code: string }): string {
  return `${entry.market}:${entry.code}`;
}

/** Read the watchlist from localStorage, tolerating missing or invalid data. */
export function loadWatchlist(): WatchlistEntry[] {
  try {
    const raw = window.localStorage.getItem(WATCHLIST_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isEntry).map((entry) => ({
      market: entry.market,
      code: entry.code,
      name: entry.name,
      quantity: typeof entry.quantity === "number" ? entry.quantity : null,
      averageCost: typeof entry.averageCost === "number" ? entry.averageCost : null,
      memo: typeof entry.memo === "string" ? entry.memo : null,
    }));
  } catch {
    return [];
  }
}

/** Persist the watchlist to localStorage. */
export function saveWatchlist(entries: WatchlistEntry[]): void {
  try {
    window.localStorage.setItem(WATCHLIST_KEY, JSON.stringify(entries));
  } catch {
    // localStorage unavailable (private mode / quota) — keep state in memory.
  }
}

/** Add or replace an entry, keyed by market + code. */
export function upsertWatchlistEntry(
  list: WatchlistEntry[],
  entry: WatchlistEntry,
): WatchlistEntry[] {
  const key = watchlistKey(entry);
  return [...list.filter((item) => watchlistKey(item) !== key), entry];
}

/** Remove an entry by market + code. */
export function removeWatchlistEntry(
  list: WatchlistEntry[],
  target: { market: string; code: string },
): WatchlistEntry[] {
  const key = watchlistKey(target);
  return list.filter((item) => watchlistKey(item) !== key);
}
