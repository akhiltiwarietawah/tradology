/** Keep in sync with src/strategies/renko_ichimoku/asset_registry.py */

export const RENKO_CORE_SLUGS = ["eth", "sol", "xrp"] as const;

/** Group A — primary 11 (core 3 + these 8 alts). */
export const RENKO_GROUP_A_ALT_SLUGS = [
  "btc",
  "bnb",
  "doge",
  "ada",
  "trx",
  "avax",
  "link",
  "hype",
] as const;

/** Group B — extension 8. */
export const RENKO_GROUP_B_SLUGS = [
  "sui",
  "inj",
  "near",
  "apt",
  "pepe",
  "wif",
  "ena",
  "jup",
] as const;

/** Group C — exploratory 13. */
export const RENKO_GROUP_C_SLUGS = [
  "ton",
  "dot",
  "atom",
  "ltc",
  "bch",
  "uni",
  "aave",
  "pol",
  "sei",
  "tia",
  "op",
  "arb",
  "paxg",
] as const;

/** ZEC — separate watchlist (not A/B/C). */
export const RENKO_ZEC_SLUGS = ["zec"] as const;

/** @deprecated use RENKO_GROUP_A_ALT_SLUGS */
export const RENKO_ALT_SLUGS = RENKO_GROUP_A_ALT_SLUGS;

export type RenkoCoreSlug = (typeof RENKO_CORE_SLUGS)[number];
export type RenkoGroupAAltSlug = (typeof RENKO_GROUP_A_ALT_SLUGS)[number];
export type RenkoGroupBSlug = (typeof RENKO_GROUP_B_SLUGS)[number];
export type RenkoGroupCSlug = (typeof RENKO_GROUP_C_SLUGS)[number];
export type RenkoZecSlug = (typeof RENKO_ZEC_SLUGS)[number];
export type RenkoSlug =
  | RenkoCoreSlug
  | RenkoGroupAAltSlug
  | RenkoGroupBSlug
  | RenkoGroupCSlug
  | RenkoZecSlug;

export const RENKO_ALL_ALT_SLUGS: RenkoSlug[] = [
  ...RENKO_GROUP_A_ALT_SLUGS,
  ...RENKO_GROUP_B_SLUGS,
  ...RENKO_GROUP_C_SLUGS,
  ...RENKO_ZEC_SLUGS,
];

export function renkoStrategyCode(slug: RenkoSlug): string {
  return `renko_ichimoku_${slug}`;
}

export const RENKO_DEFAULT_SIZING_BASE_USD = 50;

export const RENKO_GROUP_LABELS = {
  A: "Group A — Primary 11",
  B: "Group B — Extension 8",
  C: "Group C — Exploratory 13",
  ZEC: "ZEC — Watchlist (separate)",
} as const;
