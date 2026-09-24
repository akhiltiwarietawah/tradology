import {
  RENKO_CORE_SLUGS,
  RENKO_GROUP_A_ALT_SLUGS,
  RENKO_GROUP_B_SLUGS,
  RENKO_GROUP_C_SLUGS,
  RENKO_ZEC_SLUGS,
  renkoStrategyCode,
  type RenkoSlug,
} from "@/lib/renko-assets";

export type EngineStrategySlug = RenkoSlug | "strangle";

export type EngineStrategyKind = "renko" | "strangle";

export type RenkoSnapshotKey = `renko_ichimoku_${RenkoSlug}`;

export interface EngineStrategyDef {
  slug: EngineStrategySlug;
  label: string;
  shortLabel: string;
  code: string;
  kind: EngineStrategyKind;
  snapshotKey?: RenkoSnapshotKey;
}

const RENKO_LABELS: Record<RenkoSlug, string> = {
  eth: "ETH",
  sol: "SOL",
  xrp: "XRP",
  btc: "BTC",
  bnb: "BNB",
  doge: "DOGE",
  ada: "ADA",
  trx: "TRX",
  avax: "AVAX",
  link: "LINK",
  hype: "HYPE",
  sui: "SUI",
  inj: "INJ",
  near: "NEAR",
  apt: "APT",
  pepe: "PEPE",
  wif: "WIF",
  ena: "ENA",
  jup: "JUP",
  ton: "TON",
  dot: "DOT",
  atom: "ATOM",
  ltc: "LTC",
  bch: "BCH",
  uni: "UNI",
  aave: "AAVE",
  pol: "POL",
  sei: "SEI",
  tia: "TIA",
  op: "OP",
  arb: "ARB",
  paxg: "PAXG",
  zec: "ZEC",
};

function renkoDef(slug: RenkoSlug): EngineStrategyDef {
  const label = RENKO_LABELS[slug];
  const code = renkoStrategyCode(slug);
  return {
    slug,
    label: `Renko ${label}`,
    shortLabel: label,
    code,
    kind: "renko",
    snapshotKey: code as RenkoSnapshotKey,
  };
}

export const ENGINE_STRATEGIES: EngineStrategyDef[] = [
  ...RENKO_CORE_SLUGS.map(renkoDef),
  ...RENKO_GROUP_A_ALT_SLUGS.map(renkoDef),
  ...RENKO_GROUP_B_SLUGS.map(renkoDef),
  ...RENKO_GROUP_C_SLUGS.map(renkoDef),
  ...RENKO_ZEC_SLUGS.map(renkoDef),
  {
    slug: "strangle",
    label: "BTC Strangle",
    shortLabel: "Strangle",
    code: "short_strangle",
    kind: "strangle",
  },
];

export function getEngineStrategy(slug: string | undefined): EngineStrategyDef | undefined {
  return ENGINE_STRATEGIES.find((s) => s.slug === slug);
}
