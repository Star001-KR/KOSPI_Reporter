/**
 * Browser-local watchlist storage (MVP-09).
 *
 * A visitor's watchlist and holdings (quantity / average cost / memo) live only
 * in this browser via localStorage. The server stores public research data
 * (news, disclosures, analysis) but never a visitor's personal portfolio.
 *
 * Storage is scoped per signed-in account, so two people sharing one browser
 * never see each other's watchlist, holdings, or read history.
 */

import type { WatchlistEntry } from "./types";

const WATCHLIST_KEY = "kospi.watchlist.v1";
const READ_ITEMS_KEY = "kospi.read-items.v1";
const THEME_KEY = "kospi.theme.v1";
const BOOKMARK_KEY = "kospi.bookmarks.v1";

/** Per-account localStorage key, so one visitor's data never loads for another. */
function scopedKey(base: string, scope: string): string {
  return `${base}::${scope}`;
}

/**
 * Move a pre-per-account (unscoped) key onto the first account to sign in after
 * this upgrade, so an existing visitor keeps their watchlist instead of starting
 * empty. The legacy key is then removed so a second account on the same browser
 * cannot adopt the same data.
 */
function adoptLegacyKey(base: string, scope: string): void {
  try {
    const target = scopedKey(base, scope);
    if (window.localStorage.getItem(target) !== null) return;
    const legacy = window.localStorage.getItem(base);
    if (legacy === null) return;
    window.localStorage.setItem(target, legacy);
    window.localStorage.removeItem(base);
  } catch {
    // localStorage unavailable — nothing to migrate.
  }
}

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

/** Read an account's watchlist from localStorage, tolerating missing or invalid data. */
export function loadWatchlist(scope: string): WatchlistEntry[] {
  adoptLegacyKey(WATCHLIST_KEY, scope);
  try {
    const raw = window.localStorage.getItem(scopedKey(WATCHLIST_KEY, scope));
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

/** Persist an account's watchlist to localStorage. */
export function saveWatchlist(scope: string, entries: WatchlistEntry[]): void {
  try {
    window.localStorage.setItem(
      scopedKey(WATCHLIST_KEY, scope),
      JSON.stringify(entries),
    );
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

/** Read the set of feed issue ids the account has already opened. */
export function loadReadIds(scope: string): Set<string> {
  adoptLegacyKey(READ_ITEMS_KEY, scope);
  try {
    const raw = window.localStorage.getItem(scopedKey(READ_ITEMS_KEY, scope));
    if (!raw) return new Set();
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(
      parsed.filter((value): value is string => typeof value === "string"),
    );
  } catch {
    return new Set();
  }
}

/** Persist an account's set of opened feed issue ids. */
export function saveReadIds(scope: string, ids: Set<string>): void {
  try {
    window.localStorage.setItem(
      scopedKey(READ_ITEMS_KEY, scope),
      JSON.stringify([...ids]),
    );
  } catch {
    // localStorage unavailable (private mode / quota) — keep state in memory.
  }
}

/** Read the set of feed issue ids the account has bookmarked. */
export function loadBookmarkIds(scope: string): Set<string> {
  try {
    const raw = window.localStorage.getItem(scopedKey(BOOKMARK_KEY, scope));
    if (!raw) return new Set();
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(
      parsed.filter((value): value is string => typeof value === "string"),
    );
  } catch {
    return new Set();
  }
}

/** Persist an account's set of bookmarked feed issue ids. */
export function saveBookmarkIds(scope: string, ids: Set<string>): void {
  try {
    window.localStorage.setItem(
      scopedKey(BOOKMARK_KEY, scope),
      JSON.stringify([...ids]),
    );
  } catch {
    // localStorage unavailable (private mode / quota) — keep state in memory.
  }
}

/**
 * The device's OS-level light / dark preference, used as the theme default
 * until an account explicitly picks one.
 */
export function deviceTheme(): "light" | "dark" {
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  } catch {
    return "light";
  }
}

/** Read an account's saved theme, falling back to the device preference. */
export function loadTheme(scope: string): "light" | "dark" {
  try {
    const saved = window.localStorage.getItem(scopedKey(THEME_KEY, scope));
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    // localStorage unavailable — fall through to the device preference.
  }
  return deviceTheme();
}

/** Persist an account's light / dark theme choice. */
export function saveTheme(scope: string, theme: "light" | "dark"): void {
  try {
    window.localStorage.setItem(scopedKey(THEME_KEY, scope), theme);
  } catch {
    // localStorage unavailable (private mode / quota) — keep state in memory.
  }
}
