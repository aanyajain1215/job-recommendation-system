/**
 * Currency-aware salary formatting.
 *
 * Uses provided currency when available. If missing/ambiguous, infers from
 * location (e.g. Indian locations -> INR/₹). Shows appropriate symbols per currency.
 */

const SYMBOLS: Record<string, string> = {
  USD: "$",
  EUR: "€",
  GBP: "£",
  JPY: "¥",
  AUD: "A$",
  CAD: "C$",
  INR: "₹",
  AED: "AED ",
  SGD: "S$",
  CHF: "CHF ",
};

const INDIA_HINTS = [
  "india",
  "bangalore",
  "bengaluru",
  "mumbai",
  "delhi",
  "new delhi",
  "gurgaon",
  "gurugram",
  "noida",
  "hyderabad",
  "pune",
  "chennai",
  "kolkata",
  "ahmedabad",
  "jaipur",
  "kochi",
  "coimbatore",
  "indore",
  "chandigarh",
  "telangana",
  "karnataka",
  "maharashtra",
  "tamil nadu",
  "uttar pradesh",
  "haryana",
  "gujarat",
  "west bengal",
  "kerala",
  "rajasthan",
];

function inferCurrency(currency?: string | null, location?: string | null): string {
  const cur = (currency || "").trim().toUpperCase();
  const loc = (location || "").toLowerCase();
  const isIndia = INDIA_HINTS.some((h) => loc.includes(h));

  if (cur === "INR") return "INR";
  if (cur && cur !== "USD") return cur; // trust explicit non-USD currency
  if (isIndia) return "INR"; // Indian location/company context -> rupees
  if (cur === "USD") return "USD";
  return "USD";
}

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
  currency?: string | null,
  location?: string | null
): string | null {
  if (min == null && max == null) return null;
  const cur = inferCurrency(currency, location);

  if (min != null && max != null && min !== max) {
    return `${formatPart(min, cur)} – ${formatPart(max, cur)}`;
  }
  return formatPart((min ?? max) as number, cur);
}

// ---------------------------------------------------------------------------
// Match tiers (shown instead of a raw "% match")
// ---------------------------------------------------------------------------
// The backend's match_score is a calibrated probability of applying, so real
// values are low (mostly 5-30%). Tiers are relative to the average apply rate:
// top = 2x+ average, strong = above average, possible = below. Measured on
// held-out users: top 52% applied, strong 24%, possible 10%.

export type MatchTier = "top" | "strong" | "possible";

export const MATCH_TIER_META: Record<
  MatchTier,
  { label: string; hint: string; badge: string; ring: string; rank: number }
> = {
  top: {
    label: "Top match",
    hint: "At least 2x more likely than an average job to be one you would apply to",
    badge: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
    ring: "border-emerald-500/20 hover:border-emerald-500/40",
    rank: 3,
  },
  strong: {
    label: "Strong match",
    hint: "More likely than an average job to be one you would apply to",
    badge: "bg-cyan-500/10 text-cyan-600 border-cyan-500/30",
    ring: "border-cyan-500/20 hover:border-cyan-500/40",
    rank: 2,
  },
  possible: {
    label: "Possible match",
    hint: "Less likely than an average job, but still related to your profile",
    badge: "bg-zinc-800 text-zinc-300 border-zinc-700",
    ring: "border-zinc-800/80 hover:border-zinc-700",
    rank: 1,
  },
};

/** Tier for a recommendation; falls back to the old score bands for older backends. */
export function matchTierOf(item: { match_tier?: MatchTier | null; match_score: number }): MatchTier {
  if (item.match_tier) return item.match_tier;
  if (item.match_score >= 70) return "top";
  if (item.match_score >= 40) return "strong";
  return "possible";
}
