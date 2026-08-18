/** Shared formatting + series utilities — one CU/USD/date treatment everywhere. */

export interface DailyPoint {
  date: string; // YYYY-MM-DD
  requests: number;
}

/** Zero-fill a daily series to a contiguous `days`-long window ending today
 * (UTC). The backend omits days with no traffic; charts must not — 3 bars
 * spread across a "14d" axis reads as steady traffic. */
export function zeroFillDaily<T extends DailyPoint>(
  points: T[],
  days: number,
  empty: Omit<T, "date">,
): T[] {
  const byDate = new Map(points.map((p) => [p.date, p]));
  const out: T[] = [];
  const now = new Date();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() - i));
    const key = d.toISOString().slice(0, 10);
    out.push(byDate.get(key) ?? ({ date: key, ...empty } as T));
  }
  return out;
}

/** One canonical CU rendering: enough precision to never show a real value
 * as zero, no scientific notation (operators read dollars, not exponents). */
export function fmtCU(cu: number): string {
  if (!cu) return "0";
  if (cu >= 1) return cu.toFixed(2);
  if (cu >= 0.01) return cu.toFixed(4);
  return cu.toFixed(6);
}

/** CU → USD string when the conversion rate is known (cu_to_usd from config). */
export function cuToUsd(cu: number, cuToUsdRate: number | null): string | null {
  if (cuToUsdRate == null || !Number.isFinite(cuToUsdRate)) return null;
  const usd = cu * cuToUsdRate;
  if (usd === 0) return "$0";
  if (usd >= 0.01) return `$${usd.toFixed(2)}`;
  return `$${usd.toFixed(5)}`;
}

/** Pricing-row unit suffix — rate_unit is data, not always per-1M-tokens. */
export function rateUnitSuffix(rateUnit: string | null): string {
  switch (rateUnit) {
    case "per_1k_tokens": return "/1K tok";
    case "per_1m_characters": return "/1M chars";
    case "per_image": return "/image";
    case "per_minute": return "/min";
    case "per_1m_tokens":
    default: return "/1M";
  }
}

/** Rate formatting that never rounds a real price to $0.00. */
export function fmtRate(r: number | null): string {
  if (r == null) return "—";
  if (r === 0) return "$0";
  if (r >= 1) return `$${r % 1 === 0 ? r.toFixed(0) : r.toFixed(2)}`;
  if (r >= 0.01) return `$${r.toFixed(2)}`;
  return `$${r.toFixed(4)}`;
}
