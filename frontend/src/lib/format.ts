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
