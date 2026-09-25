/**
 * Currency-aware salary formatting.
 *
 * The job cards used to hardcode `$…k` regardless of `salary_currency`,
 * which rendered Indian salaries (e.g. ₹300,000–1,200,000) as "$300k–$1200k".
 * Adzuna /in/ postings are stored as INR after the ingest currency fix.
 */

const SYMBOLS: Record<string, string> = {
  USD: "$",
  EUR: "€",
  GBP: "£",
  JPY: "¥",
  AUD: "A$",
  CAD: "C$",
};

/** Compact number: 1500000 -> "1.5", 300000 -> "3" (trailing .0 dropped). */
function compact(value: number): string {
  const rounded = Math.round(value * 100) / 100;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
}

function formatPart(value: number, currency: string): string {
  if (currency === "INR") {
    // Indian convention: lakh / crore rather than thousands
    if (Math.abs(value) >= 1e7) return `₹${compact(value / 1e7)}Cr`;
    if (Math.abs(value) >= 1e5) return `₹${compact(value / 1e5)}L`;
    return `₹${Math.round(value).toLocaleString("en-IN")}`;
  }
  const symbol = SYMBOLS[currency] ?? `${currency} `;
  if (Math.abs(value) >= 1000) return `${symbol}${compact(value / 1000)}k`;
  return `${symbol}${Math.round(value).toLocaleString("en-US")}`;
}

/**
 * Annual salary range for display, e.g. `₹3L – ₹12L`, `$80k – $120k`.
 * Returns `null` when neither bound is present (caller shows "Competitive salary").
 */
export function formatSalary(
  min?: number | null,
  max?: number | null,
  currency?: string | null
): string | null {
  if (min == null && max == null) return null;
  const cur = (currency || "USD").toUpperCase();

  if (min != null && max != null && min !== max) {
    return `${formatPart(min, cur)} – ${formatPart(max, cur)}`;
  }
  return formatPart((min ?? max) as number, cur);
}
