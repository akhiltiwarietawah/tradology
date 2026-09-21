/** Keep in sync with src/strategies/renko_ichimoku/asset_registry.py */

export const RENKO_CORE_SLUGS = ["eth", "sol", "xrp"] as const;

export const RENKO_ALT_SLUGS = [
  "btc",
  "bnb",
  "doge",
  "ada",
  "trx",
  "avax",
  "link",
  "hype",
] as const;

export type RenkoCoreSlug = (typeof RENKO_CORE_SLUGS)[number];
export type RenkoAltSlug = (typeof RENKO_ALT_SLUGS)[number];
export type RenkoSlug = RenkoCoreSlug | RenkoAltSlug;

export function renkoStrategyCode(slug: RenkoSlug): string {
  return `renko_ichimoku_${slug}`;
}

export const RENKO_DEFAULT_SIZING_BASE_USD = 50;
